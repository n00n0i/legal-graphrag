"""
Legal GraphRAG — Graph Ingestion Service
========================================
รวม pipeline: PDF → Parse → Extract → Store (Neo4j + Qdrant)

Usage:
  from ingestion import LawIngestionService
  
  service = LawIngestionService(
      neo4j_uri="bolt://localhost:7687",
      qdrant_url="http://localhost:6333",
      openai_api_key="sk-..."
  )
  service.run("/path/to/law.pdf", law_id="forest_act_4_2567")
"""

import uuid
from datetime import datetime
from typing import Optional, Literal
from pathlib import Path

from neo4j import GraphDatabase
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct
from qdrant_client.http.exceptions import UnexpectedResponse

from document_parser import PDFLawParser, PDFGeneralParser, OCSLawFetcher, ParsedSection
from entity_extractor import LawEntityExtractor, Embedder
from llm_prompts import LawEntities
from qdrant_schema import QDRANT_COLLECTIONS, qdrant_access_filter
from neo4j_schema import (
    Law, Section, Penalty, Right, Duty, Authority, Subject,
    Amendment, LegalReference, Org, GeoLocation,
    RELATIONSHIPS, NEO4J_INDEXES, NEO4J_CONSTRAINTS, AccessLevel
)


# ─── Neo4j Driver ─────────────────────────────────────────────────────────────

class Neo4jDriver:
    """Neo4j connection + helpers"""
    
    def __init__(self, uri: str, user: str = "neo4j", password: str = "neo4j123"):
        self.uri = uri
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def close(self):
        self.driver.close()
    
    def execute(self, query: str, params: dict = {}):
        with self.driver.session() as session:
            result = session.run(query, params)
            return list(result)
    
    def execute_write(self, query: str, params: dict = {}):
        with self.driver.session() as session:
            return session.run(query, params)
    
    def init_schema(self):
        """Create indexes and constraints"""
        for constraint in NEO4J_CONSTRAINTS:
            try:
                self.execute_write(constraint)
                print(f"  ✓ Created constraint")
            except Exception as e:
                print(f"  ⚠ Constraint: {e}")
        
        for index in NEO4J_INDEXES:
            try:
                self.execute_write(index)
                print(f"  ✓ Created index")
            except Exception as e:
                print(f"  ⚠ Index: {e}")
    
    def upsert_law(self, law: Law) -> str:
        """Insert or update a Law node"""
        query = """
        MERGE (l:Law {law_id: $law_id})
        SET l.title = $title,
            l.law_type = $law_type,
            l.effective_date = $effective_date,
            l.gazette_date = $gazette_date,
            l.issued_by = $issued_by,
            l.agency_responsible = $agency_responsible,
            l.access_level = $access_level,
            l.parent_law_id = $parent_law_id,
            l.related_laws = $related_laws,
            l.source_url = $source_url,
            l.updated_at = datetime()
        RETURN l.law_id
        """
        result = self.execute_write(query, law.model_dump(exclude={"created_at"}))
        return law.law_id
    
    def upsert_section(self, law_id: str, section: dict) -> str:
        """Insert or update a Section node and link to Law"""
        query = """
        MERGE (l:Law {law_id: $law_id})
        MERGE (s:Section {section_id: $section_id})
        SET s.section_number = $section_number,
            s.title = $title,
            s.content = $content,
            s.chapter = $chapter,
            s.part = $part,
            s.access_level = $access_level,
            s.updated_at = datetime()
        MERGE (l)-[r:HAS_SECTION]->(s)
        RETURN s.section_id
        """
        self.execute_write(query, section)
        
        # Also link to law for easy lookup
        rel_query = """
        MATCH (l:Law {law_id: $law_id}), (s:Section {section_id: $section_id})
        MERGE (l)-[:HAS_SECTION]->(s)
        """
        self.execute_write(rel_query, {"law_id": law_id, "section_id": section["section_id"]})
        return section["section_id"]
    
    def upsert_penalty(self, section_id: str, penalty: dict) -> str:
        """Insert Penalty and link to Section"""
        query = """
        MATCH (s:Section {section_id: $section_id})
        MERGE (p:Penalty {penalty_id: $penalty_id})
        SET p.offense_description = $offense_description,
            p.penalty_type = $penalty_type,
            p.penalty_value = $penalty_value,
            p.imprisonment_range = $imprisonment_range,
            p.fine_range = $fine_range,
            p.updated_at = datetime()
        MERGE (s)-[r:SECTION_HAS_PENALTY]->(p)
        """
        self.execute_write(query, {
            "section_id": section_id,
            **penalty
        })
        return penalty.get("penalty_id", "")
    
    def upsert_relationship(self, from_id: str, from_label: str, 
                            to_id: str, to_label: str, rel_type: str):
        """Create relationship between two nodes"""
        query = f"""
        MATCH (a:{from_label} {{{from_label.lower()}_id: $from_id}})
        MATCH (b:{to_label} {{{to_label.lower()}_id: $to_id}})
        MERGE (a)-[r:{rel_type}]->(b)
        """
        self.execute_write(query, {"from_id": from_id, "to_id": to_id})
    
    def query_by_access(self, label: str, role: str, property_filter: dict = {}):
        """Query nodes filtered by access level"""
        allowed_levels = qdrant_access_filter(role)
        
        filter_parts = [f"n.access_level IN {allowed_levels}"]
        for k, v in property_filter.items():
            filter_parts.append(f"n.{k} = '{v}'")
        
        where_clause = " AND ".join(filter_parts)
        
        query = f"""
        MATCH (n:{label})
        WHERE {where_clause}
        RETURN n
        LIMIT 100
        """
        return self.execute(query)


# ─── Qdrant Driver ────────────────────────────────────────────────────────────

class QdrantDriver:
    """Qdrant connection + helpers"""
    
    def __init__(self, url: str, api_key: Optional[str] = None):
        self.client = QdrantClient(url=url, api_key=api_key)
        self._ensure_collections()
    
    def _ensure_collections(self):
        """Create collections if not exist"""
        for name, config in QDRANT_COLLECTIONS.items():
            try:
                self.client.get_collection(name)
            except (UnexpectedResponse, Exception):
                print(f"  Creating Qdrant collection: {name}")
                self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=config["vectors"]["size"],
                        distance=Distance[config["vectors"]["distance"]]
                    )
                )
    
    def upsert_law_chunks(self, law_id: str, chunks: list[dict], vectors: list[list[float]]):
        """Insert law chunks with vectors"""
        points = []
        for i, (chunk, vector) in enumerate(zip(chunks, vectors)):
            point_id = str(uuid.uuid4())
            payload = {
                "chunk_id": chunk["chunk_id"],
                "source_law_id": law_id,
                "source_section_id": chunk.get("section_id"),
                "law_title": chunk.get("law_title", ""),
                "law_type": chunk.get("law_type", ""),
                "chunk_index": i,
                "access_level": chunk.get("access_level", "PUBLIC"),
                "chapter": chunk.get("chapter"),
                "part": chunk.get("part"),
                "effective_date": chunk.get("effective_date"),
                "created_at": datetime.utcnow().isoformat(),
            }
            points.append(PointStruct(
                id=point_id,
                vector=vector,
                payload=payload
            ))
        
        self.client.upsert(collection_name="law_chunks", points=points)
    
    def search(self, collection: str, query_vector: list[float],
               role: str, limit: int = 10, filters: dict = {}):
        """Search with access-level filtering"""
        allowed_levels = qdrant_access_filter(role)
        
        from qdrant_client.models import Filter, FieldCondition, MatchAny
        
        filter_conditions = [
            FieldCondition(
                key="access_level",
                match=MatchAny(any=allowed_levels)
            )
        ]
        
        for key, value in filters.items():
            filter_conditions.append(
                FieldCondition(key=key, match=value)
            )
        
        results = self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=Filter(must=filter_conditions),
            limit=limit
        )
        
        return results


# ─── Main Ingestion Service ───────────────────────────────────────────────────

class LawIngestionService:
    """
    รวม pipeline ทั้งหมด: download → parse → extract → store
    
    Usage:
      service = LawIngestionService(...)
      result = service.run("/path/to/law.pdf")
    """
    
    def __init__(
        self,
        neo4j_uri: str = "bolt://localhost:7687",
        neo4j_user: str = "neo4j",
        neo4j_password: str = "neo4j123",
        qdrant_url: str = "http://localhost:6333",
        qdrant_api_key: Optional[str] = None,
        llm_provider: str = "openai",
        llm_api_key: Optional[str] = None,
        embed_provider: str = "openai",
        embed_api_key: Optional[str] = None,
    ):
        # Init drivers
        self.neo4j = Neo4jDriver(neo4j_uri, neo4j_user, neo4j_password)
        self.qdrant = QdrantDriver(qdrant_url, qdrant_api_key)
        
        # Init extractors
        self.extractor = LawEntityExtractor(
            provider=llm_provider,
            api_key=llm_api_key,
        )
        self.embedder = Embedder(
            provider=embed_provider,
            api_key=embed_api_key,
        )
        
        # Init parsers
        self.law_parser = PDFLawParser()
        self.general_parser = PDFGeneralParser()
    
    def run(self, pdf_path: str, law_id: Optional[str] = None) -> dict:
        """Full ingestion pipeline for a law PDF"""
        print(f"[Ingestion] Starting: {pdf_path}")
        
        # 1. Parse
        print("  [1] Parsing PDF...")
        parsed = self.law_parser.parse(pdf_path, law_id)
        print(f"       Found {len(parsed.sections)} sections, {parsed.page_count} pages")
        
        # 2. Store in Neo4j
        print("  [2] Storing entities in Neo4j...")
        self._store_law_entities(parsed)
        
        # 3. Generate chunks + embeddings + Qdrant
        print("  [3] Generating chunks + vectors → Qdrant...")
        self._store_chunks(parsed)
        
        print(f"[Ingestion] Done: {parsed.law_id}")
        return {
            "law_id": parsed.law_id,
            "title": parsed.title,
            "sections": len(parsed.sections),
            "chunks": len(parsed.sections),  # 1 chunk per section
        }
    
    def _store_law_entities(self, parsed):
        """Store law + sections + penalties in Neo4j"""
        # Upsert law
        law_node = Law(
            law_id=parsed.law_id,
            title=parsed.title,
            law_type=parsed.law_type,
            effective_date=parsed.effective_date,
            gazette_date=parsed.gazette_date,
            source_url=parsed.source_path,
            access_level=AccessLevel.PUBLIC,
        )
        self.neo4j.upsert_law(law_node)
        
        # Upsert sections
        for sec in parsed.sections:
            section_data = {
                "section_id": f"{parsed.law_id}_s{sec.section_number}",
                "section_number": sec.section_number,
                "title": sec.title,
                "content": sec.content,
                "chapter": sec.chapter,
                "part": sec.part,
                "access_level": "PUBLIC",
            }
            self.neo4j.upsert_section(parsed.law_id, section_data)
        
        # TODO: Call LLM to extract penalties per section
        # For now, skip LLM extraction to avoid API cost
    
    def _store_chunks(self, parsed):
        """Generate embeddings and store in Qdrant"""
        chunks = []
        vectors = []
        
        for i, sec in enumerate(parsed.sections):
            # Clean content for embedding
            embed_text = sec.content[:1500]
            
            try:
                vec = self.embedder.embed(embed_text)
            except Exception as e:
                print(f"     Warning: embed failed for {sec.section_number}: {e}")
                vec = [0.0] * 1024
            
            chunks.append({
                "chunk_id": f"{parsed.law_id}_chunk_{i:04d}",
                "section_id": f"{parsed.law_id}_s{sec.section_number}",
                "law_title": parsed.title,
                "law_type": parsed.law_type,
                "access_level": "PUBLIC",
                "chapter": sec.chapter,
                "part": sec.part,
                "effective_date": parsed.effective_date,
            })
            vectors.append(vec)
        
        self.qdrant.upsert_law_chunks(parsed.law_id, chunks, vectors)
    
    def run_from_ocs(self, file_id: str, filename: str) -> dict:
        """Download from OCS then run ingestion"""
        fetcher = OCSLawFetcher()
        pdf_path = fetcher.download_law(file_id, filename)
        return self.run(pdf_path)
    
    def close(self):
        self.neo4j.close()


# ─── CLI Entry Point ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python ingestion.py run /path/to/law.pdf [law_id]")
        print("  python ingestion.py ocs <file_id> <filename.pdf>")
        print("  python ingestion.py init-schema")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "init-schema":
        print("=== Initializing Neo4j Schema ===")
        neo = Neo4jDriver("bolt://localhost:7687")
        neo.init_schema()
        neo.close()
        print("Done.")
    
    elif cmd == "run":
        pdf_path = sys.argv[2]
        law_id = sys.argv[3] if len(sys.argv) > 3 else None
        
        service = LawIngestionService(
            neo4j_uri="bolt://localhost:7687",
            qdrant_url="http://localhost:6333",
        )
        
        result = service.run(pdf_path, law_id)
        print(f"Result: {result}")
        service.close()
    
    elif cmd == "ocs":
        file_id = sys.argv[2]
        filename = sys.argv[3]
        
        service = LawIngestionService(
            neo4j_uri="bolt://localhost:7687",
            qdrant_url="http://localhost:6333",
        )
        
        result = service.run_from_ocs(file_id, filename)
        print(f"Result: {result}")
        service.close()
    
    else:
        print(f"Unknown command: {cmd}")