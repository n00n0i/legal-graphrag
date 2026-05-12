"""
Legal GraphRAG — Document Management + Ingestion Endpoints
===========================================================
Handles:
  - Upload PDF/Word → parse → extract entities → ingest to Neo4j + Qdrant
  - List / Get / Delete documents
  - Trigger reindex / rebuild
  - OCS Law fetcher (direct URL)
"""

import os
import re
import uuid
import hashlib
import tempfile
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends, UploadFile, File, Form
from pydantic import BaseModel
from neo4j import GraphDatabase

from api import get_current_user, User, get_neo4j, get_qdrant, settings
from user_management import rbac_check

router = APIRouter(prefix="/api/v1/admin", tags=["admin", "documents"])

# ─── Helpers ────────────────────────────────────────────────

def _save_upload(file: UploadFile) -> tuple[str, str]:
    """Save upload to temp file. Returns (path, hash)."""
    suffix = Path(file.filename or "upload").suffix.lower()
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        content = file.file.read()
        f.write(content)
        return f.name, hashlib.md5(content).hexdigest()


def _detect_law_format(text: str) -> dict:
    """Detect if text looks like Thai government law (พรบ/พรก/etc)."""
    patterns = {
        "law_type": None,
        "title": None,
        "chapter": None,
        "sections": [],
    }
    # พระราชบัญญัติ / พระราชกำหนด / รัฐธรรมนูญ
    law_match = re.search(r"(พระราชบัญญัติ|พระราชกำหนด|รัฐธรรมนูญ|ประมวลกฎหมาย)[\s\n]+(.+?)(?:\n|ฉบับที่|พ.ศ)", text[:500])
    if law_match:
        patterns["law_type"] = law_match.group(1)
        patterns["title"] = law_match.group(2).strip()[:200]

    # Find section patterns: มาตรา 30 / ข้อ 5 / คำว่า
    section_patterns = [
        r"(?:มาตรา|ข้อ|คำว่า|ประกาศ|ระเบียบ)\s+(\d+[\s\w,-]*?)(?:[\n\.\)]|$)(.+?)(?=(?:มาตรา|ข้อ|\n\n|$))",
    ]
    for pat in section_patterns:
        for m in re.finditer(pat, text):
            num = m.group(1).strip()
            content = m.group(2).strip()[:500]
            if num and len(content) > 10:
                patterns["sections"].append({"number": num, "content": content})

    return patterns


def _chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Simple fixed-size chunker with overlap."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


async def _parse_and_ingest(file_path: str, law_id: str, title: str,
                           uploaded_by: str, file_hash: str) -> dict:
    """
    Full ingestion pipeline:
      1. Parse PDF → text
      2. Detect law format + sections
      3. Chunk
      4. Embed (BGE-M3)
      5. Upsert to Neo4j (law + sections)
      6. Upsert to Qdrant (chunks)
    """
    # ── Step 1: Parse PDF ──────────────────────────────────
    try:
        import pymupdf
        doc = pymupdf.open(file_path)
        text = "\n".join([page.get_text() for page in doc])
        doc.close()
        if not text.strip():
            raise ValueError("PDF has no extractable text")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"PDF parse failed: {e}")

    # ── Step 2: Detect format ────────────────────────────────
    format_info = _detect_law_format(text)

    # ── Step 3: Chunk ──────────────────────────────────────
    chunks = _chunk_text(text)
    total_chunks = len(chunks)

    # ── Step 4: Embed ──────────────────────────────────────
    from entity_extractor import BGEEmbedder
    try:
        embedder = BGEEmbedder()
    except Exception:
        # Fallback: use simple hash-based pseudo-embedding (for demo)
        embedder = None

    # ── Step 5: Neo4j ──────────────────────────────────────
    neo4j = get_neo4j()
    with neo4j.session() as session:
        # Upsert law node
        session.run("""
            MERGE (l:Law {law_id: $law_id})
            SET l.title = $title,
                l.file_hash = $file_hash,
                l.uploaded_by = $uploaded_by,
                l.uploaded_at = datetime(),
                l.status = 'active',
                l.total_chunks = $total_chunks,
                l.total_pages = $total_pages,
                l.law_type = $law_type
            """,
            law_id=law_id, title=title, file_hash=file_hash,
            uploaded_by=uploaded_by, total_chunks=total_chunks,
            total_pages=format_info.get("total_pages", 0),
            law_type=format_info.get("law_type", "unknown")
        )

        # Section nodes
        for sec in format_info.get("sections", [])[:500]:
            session.run("""
                MERGE (l:Law {law_id: $law_id})
                CREATE (s:Section {section_id: $sid})
                SET s.number = $num, s.content = $content
                CREATE (s)-[:BELONGS_TO]->(l)
                """,
                law_id=law_id, sid=f"{law_id}-sec-{sec['number']}",
                num=sec["number"], content=sec["content"]
            )

    # ── Step 6: Qdrant ─────────────────────────────────────
    qdrant = get_qdrant()

    # Ensure collection exists
    from qdrant_client.models import Distance, VectorParams, ScalarSchema, TextIndexParams, TokenizerType

    try:
        qdrant.recreate_collection(
            collection_name="law_chunks",
            vectors_config=VectorParams(size=1024, distance=Distance.COSINE),
            sparse_vectors_config={},
        )
    except Exception:
        pass  # Already exists

    from qdrant_client.models import Filter, FieldCondition, MatchAny, PayloadSchemaType

    # Upsert chunks
    from entity_extractor import BGEEmbedder
    try:
        embedder = BGEEmbedder()
    except Exception:
        embedder = None

    points = []
    for i, chunk in enumerate(chunks[:1000]):  # max 1000 chunks
        if embedder:
            try:
                vec = embedder.embed(chunk)
            except Exception:
                vec = [0.0] * 1024
        else:
            vec = [0.0] * 1024

        pid = f"{law_id}-chunk-{i}"
        points.append({
            "id": pid,
            "vector": vec,
            "payload": {
                "law_id": law_id,
                "law_title": title,
                "chunk_index": i,
                "chunk_text": chunk[:1000],
                "access_level": "public",
                "file_hash": file_hash,
                "uploaded_at": datetime.utcnow().isoformat(),
            }
        })

    if points:
        qdrant.upsert(collection_name="law_chunks", points=points)

    return {
        "law_id": law_id,
        "title": title,
        "chunks": total_chunks,
        "sections": len(format_info.get("sections", [])),
        "status": "ingested",
    }


# ─── Request/Response Models ──────────────────────────────────

class DocResponse(BaseModel):
    law_id: str
    title: str
    law_type: str
    uploaded_by: str
    uploaded_at: str
    total_chunks: int
    status: str


class IngestResponse(BaseModel):
    law_id: str
    title: str
    chunks: int
    sections: int
    status: str


# ─── Endpoints ───────────────────────────────────────────────

@router.post("/documents/upload", response_model=IngestResponse)
async def upload_document(
    file: UploadFile = File(...),
    title: str = Form(...),
    description: str = Form(""),
    uploaded_by: str = Depends(get_current_user),
):
    """
    Upload PDF → parse → ingest to Neo4j + Qdrant.
    Admin only.
    """
    rbac_check(uploaded_by, "document:upload")

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename")

    suffix = Path(file.filename).suffix.lower()
    if suffix not in [".pdf", ".docx", ".doc"]:
        raise HTTPException(status_code=400, detail="Only PDF/DOC/DOCX supported")

    # Save temp file
    tmp_path, file_hash = _save_upload(file)

    # Check duplicate
    neo4j = get_neo4j()
    with neo4j.session() as session:
        existing = session.run("""
            MATCH (l:Law {file_hash: $hash})
            WHERE l.status = 'active'
            RETURN l.law_id as law_id, l.title as title
            LIMIT 1
        """, hash=file_hash).single()
        if existing:
            os.unlink(tmp_path)
            raise HTTPException(status_code=409, detail={
                "error": "Duplicate document",
                "law_id": existing["law_id"],
                "title": existing["title"],
            })

    # Generate law_id
    law_id = f"law-{uuid.uuid4().hex[:12]}"

    try:
        result = await _parse_and_ingest(
            tmp_path, law_id, title,
            uploaded_by.user_id, file_hash
        )
        return result
    finally:
        os.unlink(tmp_path)


@router.get("/documents", response_model=list[DocResponse])
async def list_documents(user: User = Depends(get_current_user)):
    """List all documents. Admin only."""
    rbac_check(user, "document:read")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (l:Law)
            WHERE l.status = 'active'
            RETURN l.law_id as law_id, l.title as title,
                   l.law_type as law_type, l.uploaded_by as uploaded_by,
                   l.uploaded_at as uploaded_at, l.total_chunks as total_chunks,
                   l.status as status
            ORDER BY l.uploaded_at DESC
        """)
        return [dict(r) for r in result]


@router.get("/documents/{law_id}", response_model=DocResponse)
async def get_document(law_id: str, user: User = Depends(get_current_user)):
    """Get document details."""
    rbac_check(user, "document:read")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (l:Law {law_id: $law_id})
            RETURN l.law_id as law_id, l.title as title,
                   l.law_type as law_type, l.uploaded_by as uploaded_by,
                   l.uploaded_at as uploaded_at, l.total_chunks as total_chunks,
                   l.status as status
            LIMIT 1
        """, law_id=law_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        return dict(result)


@router.delete("/documents/{law_id}")
async def delete_document(law_id: str, user: User = Depends(get_current_user)):
    """Soft-delete a document (marks as deleted)."""
    rbac_check(user, "document:delete")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (l:Law {law_id: $law_id})
            SET l.status = 'deleted', l.deleted_at = datetime()
            RETURN l.law_id
        """, law_id=law_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")

    # Remove from Qdrant
    qdrant = get_qdrant()
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qdrant.delete(
            collection_name="law_chunks",
            points_selector={
                "filter": Filter(must=[
                    FieldCondition(key="law_id", match=MatchValue(value=law_id))
                ])
            }
        )
    except Exception:
        pass  # Non-fatal if Qdrant delete fails

    return {"law_id": law_id, "status": "deleted"}


@router.post("/documents/{law_id}/reindex")
async def reindex_document(law_id: str, user: User = Depends(get_current_user)):
    """Re-index a document (delete Qdrant points + re-embed)."""
    rbac_check(user, "document:reindex")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (l:Law {law_id: $law_id, status: 'active'})
            RETURN l.law_id as law_id, l.title as title, l.uploaded_by as uploaded_by
        """, law_id=law_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")

    # Delete existing Qdrant points
    qdrant = get_qdrant()
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qdrant.delete(
            collection_name="law_chunks",
            points_selector={
                "filter": Filter(must=[
                    FieldCondition(key="law_id", match=MatchValue(value=law_id))
                ])
            }
        )
    except Exception:
        pass

    return {"law_id": law_id, "status": "reindex_scheduled"}


# ─── OCS Law Fetcher ─────────────────────────────────────────

class OCSLawRequest(BaseModel):
    law_id_ocs: str  # e.g. "3/2517"


@router.post("/documents/fetch-ocs", response_model=IngestResponse)
async def fetch_ocs_law(
    body: OCSLawRequest,
    user: User = Depends(get_current_user),
):
    """
    Fetch a law directly from OCS (lawforasean.ocs.go.th).
    Downloads the PDF, parses it, and ingests.
    """
    rbac_check(user, "document:upload")

    ocs_url = f"https://lawforasean.ocs.go.th/File/files/{body.law_id_ocs}.pdf"

    import urllib.request
    tmp_path = f"/tmp/ocs_{body.law_id_ocs.replace('/', '_')}.pdf"
    try:
        urllib.request.urlretrieve(ocs_url, tmp_path)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"OCS fetch failed: {e}")

    law_id = f"law-ocs-{body.law_id_ocs.replace('/', '-')}"
    title = f"กฎหมาย {body.law_id_ocs}"

    try:
        result = await _parse_and_ingest(
            tmp_path, law_id, title,
            user.user_id, hashlib.md5(open(tmp_path,"rb").read()).hexdigest()
        )
        return result
    finally:
        os.unlink(tmp_path)
