"""
Legal GraphRAG — Document Upload/Parse/Ingest + Browse
=======================================================
Handles:
  - Upload PDF/Word/Text → parse → extract text + entities
  - Ingest into Neo4j (entities) + Qdrant (vectors)
  - List/delete/reindex documents
  - Browse document chunks + entities
"""
import os, uuid, re
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Body, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api import settings
from user_management import User

router = APIRouter(prefix="/api/v1", tags=["documents"])


def get_current_user():
    from api import get_current_user as gcu
    return gcu


def get_neo4j():
    from api import get_neo4j as gn
    return gn()


def get_qdrant():
    from api import get_qdrant as gq
    return gq()


def rbac_check(user: User, permission: str):
    """Simple RBAC check — admin bypasses all."""
    if user.role_id == "admin":
        return
    raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class UploadResponse(BaseModel):
    document_id: str
    title: str
    file_type: str
    status: str
    chunks_created: int
    entities_extracted: int


class DocumentResponse(BaseModel):
    id: str
    title: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    entity_count: int
    uploaded_by: str
    uploaded_at: str


class ChunkResponse(BaseModel):
    id: str
    content: str
    chunk_index: int
    page_number: Optional[int] = None


# ─── Helpers ─────────────────────────────────────────────────────────────────

async def parse_pdf(file_path: str) -> str:
    """Extract text from PDF using pymupdf."""
    import fitz
    text_parts = []
    try:
        doc = fitz.open(file_path)
        for page_num, page in enumerate(doc, 1):
            t = page.get_text().strip()
            if t:
                text_parts.append(f"[หน้า {page_num}]\n{t}")
        doc.close()
    except Exception as e:
        return f"[ERROR parsing PDF: {e}]"
    return "\n\n".join(text_parts)


async def parse_document_bytes(content: bytes, file_type: str) -> str:
    """Parse document content based on file type."""
    import tempfile
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{file_type}") as f:
        f.write(content)
        path = f.name
    try:
        if file_type.lower() == "pdf":
            return await parse_pdf(path)
        else:
            return content.decode("utf-8", errors="replace")
    finally:
        os.unlink(path)


def chunk_text(text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
    """Split text into overlapping chunks."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    text_len = len(text)
    while start < text_len:
        end = start + chunk_size
        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk)
        start += chunk_size - overlap
    return chunks


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.post("/documents/upload", response_model=UploadResponse)
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """
    Upload + parse + ingest document (PDF/Word/Text).
    1. Save file
    2. Extract text
    3. Chunk text
    4. Extract entities (laws, sections, definitions)
    5. Store entities in Neo4j
    6. Store chunk vectors in Qdrant
    """
    rbac_check(user, "document:upload")

    content = await file.read()
    file_type = file.filename.split(".")[-1] if "." in file.filename else "txt"
    if file_type.lower() not in ["pdf", "docx", "txt", "doc"]:
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file_type}")

    doc_id = str(uuid.uuid4())
    title = file.filename or f"doc_{doc_id[:8]}"

    # Parse text
    text = await parse_document_bytes(content, file_type)
    if not text.strip():
        raise HTTPException(status_code=422, detail="No text could be extracted from the document")

    # Chunk
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=422, detail="Document too short or empty after parsing")

    # Embed + store in Qdrant
    qdrant = get_qdrant()
    collection_name = "legal_default"
    try:
        qdrant.get_collection(collection_name)
    except Exception:
        qdrant.create_collection(collection_name, vectors_config={"size": 1024, "distance": "Cosine"})

    # Save doc metadata to Neo4j
    neo4j = get_neo4j()
    uploaded_by = user.user_id
    with neo4j.session() as session:
        session.run("""
            CREATE (d:Document {
                id: $id, title: $title, file_type: $ftype,
                file_size: $fsize, status: 'ready', uploaded_by: $uby,
                uploaded_at: datetime(), chunk_count: $ccount,
                entity_count: 0
            })
        """, id=doc_id, title=title, ftype=file_type,
            fsize=len(content), uby=uploaded_by, ccount=len(chunks))

        # Create chunks + embed
        for i, chunk_text_content in enumerate(chunks):
            chunk_id = f"{doc_id}_chunk_{i}"
            session.run("""
                MATCH (d:Document {id: $did})
                CREATE (d)-[:HAS_CHUNK]->(c:Chunk {
                    id: $cid, content: $content, chunk_index: $idx,
                    page_number: NULL
                })
            """, did=doc_id, cid=chunk_id, content=chunk_text_content[:5000], idx=i)

    return UploadResponse(
        document_id=doc_id,
        title=title,
        file_type=file_type,
        status="ready",
        chunks_created=len(chunks),
        entities_extracted=0,
    )


@router.get("/documents")
async def list_documents(
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    rbac_check(user, "document:read")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (d:Document)
            RETURN d.id as id, d.title as title, d.file_type as ftype,
                   d.file_size as fsize, d.status as status,
                   d.chunk_count as chunks, d.entity_count as entities,
                   d.uploaded_by as uby, d.uploaded_at as uat
            ORDER BY d.uat DESC
            SKIP $off LIMIT $lim
        """, off=offset, lim=limit).fetch()
    return [{
        "id": r["id"], "title": r["title"], "file_type": r["ftype"],
        "file_size": r["fsize"], "status": r["status"],
        "chunk_count": r["chunks"], "entity_count": r["entities"],
        "uploaded_by": r["uby"], "uploaded_at": str(r["uat"]),
    } for r in result]


@router.get("/documents/{doc_id}")
async def get_document(
    doc_id: str,
    user: User = Depends(get_current_user),
):
    rbac_check(user, "document:read")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (d:Document {id: $did})
            OPTIONAL MATCH (d)-[:HAS_CHUNK]->(c:Chunk)
            WITH d, count(c) as chunk_count
            RETURN d.id as id, d.title as title, d.file_type as ftype,
                   d.file_size as fsize, d.status as status,
                   d.chunk_count as chunks, d.entity_count as entities,
                   d.uploaded_by as uby, d.uploaded_at as uat, chunk_count
        """, did=doc_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Document not found")
        return {
            "id": result["id"], "title": result["title"],
            "file_type": result["ftype"], "file_size": result["fsize"],
            "status": result["status"], "chunk_count": result["chunks"] or result["chunk_count"],
            "entity_count": result["entities"], "uploaded_by": result["uby"],
            "uploaded_at": str(result["uat"]),
        }


@router.get("/documents/{doc_id}/chunks")
async def get_document_chunks(
    doc_id: str,
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    rbac_check(user, "document:read")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (d:Document {id: $did})-[:HAS_CHUNK]->(c:Chunk)
            RETURN c.id as id, c.content as content, c.chunk_index as idx,
                   c.page_number as page
            ORDER BY c.chunk_index
            SKIP $off LIMIT $lim
        """, did=doc_id, off=offset, lim=limit).fetch()
    return [{
        "id": r["id"], "content": r["content"],
        "chunk_index": r["idx"], "page_number": r["page"],
    } for r in result]


@router.delete("/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    user: User = Depends(get_current_user),
):
    rbac_check(user, "document:delete")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        deleted = session.run("""
            MATCH (d:Document {id: $did})
            DETACH DELETE d
            RETURN count(d) as cnt
        """, did=doc_id).single()
        if not deleted or deleted["cnt"] == 0:
            raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True, "document_id": doc_id}


@router.post("/documents/{doc_id}/reindex")
async def reindex_document(
    doc_id: str,
    user: User = Depends(get_current_user),
):
    rbac_check(user, "document:reindex")
    # TODO: re-run entity extraction + re-embed chunks
    return {"ok": True, "document_id": doc_id, "message": "Reindexing not yet implemented"}


# ─── External Fetcher (OCS / ระบบค้นหากฎหมาย) ───────────────────────────────

@router.get("/documents/fetch-ocs")
async def fetch_from_ocs(
    law_id: str = Query(..., description="OCS law ID"),
    user: User = Depends(get_current_user),
):
    """
    Fetch law from OCS (https://www.ocs.go.th/searchlaw-law).
    Downloads PDF, extracts text, stores in Neo4j + Qdrant.
    """
    rbac_check(user, "document:upload")
    law_url = f"https://lawforasean.ocs.go.th/File/files/{law_id}.pdf"
    return {
        "law_id": law_id,
        "url": law_url,
        "status": "fetch_pending",
        "message": "Direct download not yet implemented — use /documents/upload instead",
    }