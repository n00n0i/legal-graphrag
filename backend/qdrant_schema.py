"""
Legal GraphRAG — Qdrant Collection Schema
=========================================
Vector store สำหรับ semantic search ระหว่าง law + general documents

Collections:
  1. law_chunks        — ชิ้นส่วนเอกสารกฎหมาย (by law_type)
  2. general_chunks    — ชิ้นส่วนเอกสารทั่วไป (by source_type)

Embedding: BAAI/bge-m3 1024-dim
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class LawChunk(BaseModel):
    """Chunk จากเอกสารกฎหมาย"""
    chunk_id: str
    source_law_id: str
    source_section_id: Optional[str] = None
    law_title: str
    law_type: str  # ACT, ROYAL_DECREE, CODE, etc.
    chunk_index: int  # ลำดับในเอกสาร
    chunk_text: str
    chapter: Optional[str] = None
    part: Optional[str] = None
    effective_date: Optional[str] = None
    access_level: str = "PUBLIC"  # PUBLIC, INTERNAL, REGULATED, CONFIDENTIAL, CLASSIFIED
    embed_text: str = Field(
        description="Text สำหรับ embedding — strip numbering, normalize spaces"
    )
    created_at: datetime = Field(default_factory=datetime.utcnow)


class GeneralChunk(BaseModel):
    """Chunk จากเอกสารทั่วไป"""
    chunk_id: str
    source_doc_id: str
    source_doc_title: str
    source_type: str  # PDF, DOCX, HTML, EMAIL, JSON, etc.
    chunk_index: int
    chunk_text: str
    metadata: dict = Field(default_factory=dict)  # flexible metadata
    author: Optional[str] = None
    created_date: Optional[str] = None
    access_level: str = "PUBLIC"
    embed_text: str
    tags: list[str] = Field(default_factory=list)
    org_ref: Optional[str] = None  # org_id ที่เกี่ยวข้อง
    location_ref: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ─── Qdrant Collection Configs ──────────────────────────────────────────────

QDRANT_COLLECTIONS = {
    "law_chunks": {
        "vectors": {
            "size": 1024,
            "distance": "Cosine"
        },
        "payload_schema": {
            "chunk_id": {"type": "keyword"},
            "source_law_id": {"type": "keyword"},
            "source_section_id": {"type": "keyword"},
            "law_title": {"type": "text"},
            "law_type": {"type": "keyword"},
            "law_type_raw": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "effective_date": {"type": "keyword"},
            "access_level": {"type": "keyword"},
            "chapter": {"type": "keyword"},
            "part": {"type": "keyword"},
            "created_at": {"type": "datetime"},
        },
        "retrieval_fields": ["law_title", "law_type", "access_level", "chapter"],
        "description": "Vector chunks from Thai law documents (OCS PDFs)"
    },
    "general_chunks": {
        "vectors": {
            "size": 1024,
            "distance": "Cosine"
        },
        "payload_schema": {
            "chunk_id": {"type": "keyword"},
            "source_doc_id": {"type": "keyword"},
            "source_doc_title": {"type": "text"},
            "source_type": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "author": {"type": "keyword"},
            "created_date": {"type": "keyword"},
            "access_level": {"type": "keyword"},
            "org_ref": {"type": "keyword"},
            "location_ref": {"type": "keyword"},
            "tags": {"type": "array_of_keyword"},
            "created_at": {"type": "datetime"},
        },
        "retrieval_fields": ["source_doc_title", "source_type", "access_level", "tags"],
        "description": "Vector chunks from general documents (PDF/Word/HTML/Email)"
    }
}


# ─── Access Control Filter Helper ──────────────────────────────────────────

def qdrant_access_filter(role: str) -> list[str]:
    """Return allowed access_level values for a role."""
    ACCESS_MATRIX = {
        "citizen":  ["PUBLIC"],
        "officer":  ["PUBLIC", "INTERNAL"],
        "lawyer":   ["PUBLIC", "INTERNAL", "REGULATED"],
        "admin":    ["PUBLIC", "INTERNAL", "REGULATED", "CONFIDENTIAL", "CLASSIFIED"],
    }
    return ACCESS_MATRIX.get(role, ["PUBLIC"])


# ─── Embedder Config ─────────────────────────────────────────────────────────

EMBEDDER_CONFIG = {
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "normalize": True,
    "batch_size": 32,
    "max_seq_length": 512,
}


# ─── Chunking Strategy ──────────────────────────────────────────────────────

CHUNK_STRATEGY = {
    "law": {
        "method": "section_by_section",  # แต่ละมาตรา = 1 chunk
        "overlap": 0,
        "min_chars": 50,
        "max_chars": 2000,
    },
    "general": {
        "method": "recursive_character",  # split by \n\n then merge
        "overlap": 100,
        "min_chars": 100,
        "max_chars": 1500,
    }
}


if __name__ == "__main__":
    print("=== Qdrant Collections ===")
    for name, config in QDRANT_COLLECTIONS.items():
        print(f"\n{name}:")
        print(f"  vectors: {config['vectors']}")
        print(f"  payload fields: {len(config['payload_schema'])}")
        print(f"  retrieval fields: {config['retrieval_fields']}")
    print(f"\nAccess matrix: {list(qdrant_access_filter('citizen'))} ... +3 roles")
    print(f"Embedder: {EMBEDDER_CONFIG['model']} ({EMBEDDER_CONFIG['dimension']}d)")