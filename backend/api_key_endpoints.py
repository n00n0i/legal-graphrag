"""
Legal GraphRAG — API Key Service & Document Access Control
==========================================================="""
import uuid, hashlib, secrets, base64
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel, Field
from user_management import User
from enum import Enum

router = APIRouter(prefix="/api/v1", tags=["api_key", "doc_access"])


# Import lazily to avoid circular import at module load time.
# Define as async def so FastAPI's Depends() knows to await it at request time.
# Inside, we import the real get_current_user (also async) and await it.
from fastapi import Header
from typing import Optional

async def get_current_user(authorization: Optional[str] = Header(None)):
    from api import get_current_user as gcu
    return await gcu(authorization=authorization)


def get_neo4j():
    from api import get_neo4j as gn
    return gn()


# ─── Enums ───────────────────────────────────────────────────────────────────

class ApiKeyTier(str, Enum):
    FREE = "free"; STANDARD = "standard"; PREMIUM = "premium"; ENTERPRISE = "enterprise"

class ApiKeyStatus(str, Enum):
    PENDING = "pending"; APPROVED = "approved"; REJECTED = "rejected"; REVOKED = "revoked"

class DocAccessLevel(str, Enum):
    READ = "read"; WRITE = "write"; ADMIN = "admin"

RATE_LIMITS = {
    ApiKeyTier.FREE: {"rpm": 10, "daily": 500, "monthly": 5000},
    ApiKeyTier.STANDARD: {"rpm": 60, "daily": 5000, "monthly": 50000},
    ApiKeyTier.PREMIUM: {"rpm": 300, "daily": 50000, "monthly": 500000},
    ApiKeyTier.ENTERPRISE: {"rpm": 1000, "daily": -1, "monthly": -1},
}

# ─── Helpers ─────────────────────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    raw = secrets.token_urlsafe(32)
    key = f"lgk_{raw}"
    key_hash = hashlib.sha256(key.encode()).hexdigest()
    return key, key_hash, raw

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()

# ─── Pydantic Models ─────────────────────────────────────────────────────────

class ApiKeyRequestCreate(BaseModel):
    tier: str = "free"; name: Optional[str] = None

class ApiKeyResponse(BaseModel):
    id: str; name: Optional[str]; tier: str; key: Optional[str] = None
    key_hash: Optional[str] = None; is_active: bool; expires_at: Optional[str] = None
    rate_limit_rpm: int; created_at: str; last_used_at: Optional[str] = None
    class Config: from_attributes = True

# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/user/api-key/request", response_model=dict)
async def request_api_key(body: ApiKeyRequestCreate, user: User = Depends(get_current_user)):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        existing = session.run("""
            MATCH (u:User {user_id: $uid})-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {status: 'pending'})
            RETURN r.id as id
        """, uid=user.user_id).data()
        if existing:
            raise HTTPException(status_code=409, detail="Already have a pending request")
        req_id = str(uuid.uuid4())
        tier = body.tier or "free"
        session.run("""
            MATCH (u:User {user_id: $uid})
            CREATE (u)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {
                id: $id, tier: $tier, name: $name, status: 'pending',
                created_at: datetime()
            })
        """, uid=user.user_id, id=req_id, tier=tier, name=body.name or f"{user.email}'s key")
    return {"request_id": req_id, "status": "pending"}


@router.get("/user/api-key/requests")
async def my_api_key_requests(user: User = Depends(get_current_user)):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User {user_id: $uid})-[:REQUESTED_API_KEY]->(r:ApiKeyRequest)
            RETURN r.id as id, r.tier as tier, r.name as name, r.status as status,
                   r.created_at as created_at
            ORDER BY r.created_at DESC
        """, uid=user.user_id).data()
    return [{"id": r["id"], "tier": r["tier"], "name": r["name"],
             "status": r["status"], "created_at": str(r["created_at"])} for r in result]


@router.get("/user/api-keys")
async def my_api_keys(user: User = Depends(get_current_user)):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User {user_id: $uid})-[:HAS_API_KEY]->(k:ApiKey)
            RETURN k.id as id, k.name as name, k.tier as tier, k.is_active as is_active,
                   k.expires_at as expires_at, k.rate_limit_rpm as rpm,
                   k.created_at as created_at, k.last_used_at as last_used
            ORDER BY k.created_at DESC
        """, uid=user.user_id).data()
    return [{"id": r["id"], "name": r["name"], "tier": r["tier"],
             "is_active": r["is_active"], "expires_at": str(r["expires_at"]) if r["expires_at"] else None,
             "rate_limit_rpm": r["rpm"], "created_at": str(r["created_at"]),
             "last_used_at": str(r["last_used"]) if r["last_used"] else None}
            for r in result]


@router.delete("/user/api-keys/{key_id}")
async def revoke_api_key(key_id: str, user: User = Depends(get_current_user)):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        revoked = session.run("""
            MATCH (u:User {user_id: $uid})-[:HAS_API_KEY]->(k:ApiKey {id: $kid})
            SET k.is_active = false
            RETURN k.id as id
        """, uid=user.user_id, kid=key_id).single()
        if not revoked:
            raise HTTPException(status_code=404, detail="API key not found")
    return {"ok": True}


# ─── Admin: Pending Requests ─────────────────────────────────────────────────

@router.get("/admin/api-key/requests")
async def list_pending_requests(user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {status: 'pending'})
            RETURN r.id as id, u.user_id as uid, u.email as email, u.name as uname,
                   r.tier as tier, r.name as key_name, r.created_at as created_at
            ORDER BY r.created_at ASC
        """).data()
    return [{"request_id": r["id"], "user_id": r["uid"], "email": r["email"],
             "name": r["uname"], "tier": r["tier"], "key_name": r["key_name"],
             "created_at": str(r["created_at"])} for r in result]


@router.post("/admin/api-key/approve/{request_id}")
async def approve_api_key(request_id: str, user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    key, key_hash, raw_key = generate_api_key()
    tier_name = "free"
    limits = RATE_LIMITS[ApiKeyTier.FREE]
    with neo4j.session() as session:
        req = session.run("""
            MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {id: $rid, status: 'pending'})
            RETURN r.tier as tier, r.name as kname, u.user_id as uid
        """, rid=request_id).single()
        if not req:
            raise HTTPException(status_code=404, detail="Request not found")
        tier_name = req["tier"] or "free"
        limits = RATE_LIMITS.get(ApiKeyTier(tier_name), RATE_LIMITS[ApiKeyTier.FREE])
        key_id = str(uuid.uuid4())
        session.run("""
            MATCH (u:User {user_id: $uid})-[rel:REQUESTED_API_KEY]->(r:ApiKeyRequest {id: $rid})
            DELETE rel
            CREATE (u)-[:HAS_API_KEY]->(k:ApiKey {
                id: $kid, name: $kname, tier: $tier, key_hash: $khash,
                is_active: true, rate_limit_rpm: $rpm,
                created_at: datetime(), last_used_at: NULL,
                expires_at: NULL
            })
            SET r.status = 'approved'
        """, uid=req["uid"], rid=request_id, kid=key_id, kname=req["kname"] or f"Key {key_id[:8]}",
            tier=tier_name, khash=key_hash, rpm=limits["rpm"])
    return {"api_key": key, "id": key_id, "tier": tier_name, "rate_limit_rpm": limits["rpm"]}


@router.post("/admin/api-key/reject/{request_id}")
async def reject_api_key(request_id: str, user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {id: $rid})
            SET r.status = 'rejected'
            RETURN r.id as id
        """, rid=request_id).single()
        if not result:
            raise HTTPException(status_code=404, detail="Request not found")
    return {"ok": True}


# ─── Admin: All Keys ─────────────────────────────────────────────────────────

@router.get("/admin/api-keys")
async def list_all_api_keys(user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey)
            RETURN k.id as id, u.user_id as uid, u.email as email,
                   k.name as name, k.tier as tier, k.is_active as active,
                   k.rate_limit_rpm as rpm, k.created_at as created,
                   k.last_used_at as last_used
            ORDER BY k.created_at DESC
            LIMIT 100
        """).data()
    return [{"id": r["id"], "user_id": r["uid"], "email": r["email"],
             "name": r["name"], "tier": r["tier"], "is_active": r["active"],
             "rate_limit_rpm": r["rpm"], "created_at": str(r["created"]),
             "last_used_at": str(r["last_used"]) if r["last_used"] else None}
            for r in result]


# ─── Document Access ─────────────────────────────────────────────────────────

@router.get("/admin/doc-access")
async def list_all_doc_access(user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User)-[:HAS_ACCESS]->(d:Document)
            RETURN u.user_id as uid, u.email as email, d.id as did,
                   d.title as dtitle, d.access_level as level
        """).data()
    return [{"user_id": r["uid"], "email": r["email"],
             "document_id": r["did"], "document_title": r["dtitle"],
             "access_level": r["level"]} for r in result]


@router.post("/admin/doc-access")
async def grant_doc_access(
    document_id: str = Body(...),
    user_id: str = Body(...),
    access_level: str = Body(...),
    grant_user: User = Depends(get_current_user),
):
    if grant_user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        session.run("""
            MERGE (u:User {user_id: $uid})
            MERGE (d:Document {id: $did})
            MERGE (u)-[a:HAS_ACCESS]->(d)
            SET a.level = $level, a.granted_by = $gby, a.granted_at = datetime()
        """, uid=user_id, did=document_id, level=access_level, gby=grant_user.user_id)
    return {"ok": True}


@router.delete("/admin/doc-access/{user_id}/{document_id}")
async def revoke_doc_access(
    user_id: str, document_id: str,
    user: User = Depends(get_current_user),
):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        session.run("""
            MATCH (u:User {user_id: $uid})-[a:HAS_ACCESS]->(d:Document {id: $did})
            DELETE a
        """, uid=user_id, did=document_id)
    return {"ok": True}


# ─── User: My Doc Access ─────────────────────────────────────────────────────

@router.get("/user/doc-access")
async def my_doc_access(user: User = Depends(get_current_user)):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (u:User {user_id: $uid})-[:HAS_ACCESS]->(d:Document)
            RETURN d.id as id, d.title as title, d.uploaded_by as uploaded_by,
                   d.access_level as level, d.uploaded_at as uploaded_at
        """, uid=user.user_id).data()
    return [{"document_id": r["id"], "title": r["title"],
             "uploaded_by": r["uploaded_by"], "access_level": r["level"],
             "uploaded_at": str(r["uploaded_at"]) if r["uploaded_at"] else None}
            for r in result]