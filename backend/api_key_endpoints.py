"""
Legal GraphRAG — API Key Service & Document Access Control
===========================================================
Handles:
  - API key requests (user → admin)
  - API key issuance (admin approve → raw key shown once)
  - API key authentication
  - Per-user document access grants

Auth flow:
  1. User requests API key via POST /api/v1/user/api-key/request
  2. Admin sees pending in GET /api/v1/admin/api-key/requests
  3. Admin approves → POST /api/v1/admin/api-key/approve/{id}
     → raw key returned (shown only this time)
  4. User uses key: Authorization: Bearer <api_key>
     (API key format: lgk_<base64>)
"""

import uuid
import hashlib
import secrets
import base64
from datetime import datetime, timedelta
from typing import Optional
from enum import Enum

from fastapi import APIRouter, HTTPException, Depends, Body, Query
from pydantic import BaseModel, Field

from api import get_neo4j, get_current_user, User
from user_management import user_mgr

router = APIRouter(prefix="/api/v1", tags=["api_key", "doc_access"])

# ─── Enums ───────────────────────────────────────────────────

class ApiKeyTier(str, Enum):
    FREE       = "free"
    STANDARD   = "standard"
    PREMIUM    = "premium"
    ENTERPRISE = "enterprise"

class ApiKeyStatus(str, Enum):
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED  = "revoked"

class DocAccessLevel(str, Enum):
    READ  = "read"
    WRITE = "write"
    ADMIN = "admin"

# ─── Rate Limits ─────────────────────────────────────────────

RATE_LIMITS = {
    ApiKeyTier.FREE:       {"rpm": 10,  "daily": 500,   "monthly": 5000},
    ApiKeyTier.STANDARD:   {"rpm": 60,  "daily": 5000,  "monthly": 50000},
    ApiKeyTier.PREMIUM:   {"rpm": 300, "daily": 50000, "monthly": 500000},
    ApiKeyTier.ENTERPRISE: {"rpm": 1000,"daily": -1,    "monthly": -1},
}

# ─── Helpers ─────────────────────────────────────────────────

def generate_api_key() -> tuple[str, str, str]:
    """Returns (raw_key, key_prefix, key_hash)"""
    raw = f"lgk_{base64.b64encode(secrets.token_bytes(24)).decode().rstrip('=')}"
    key_prefix = raw[:12]
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_prefix, key_hash

def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    return hashlib.sha256(raw_key.encode()).hexdigest() == stored_hash

# ─── Pydantic Models ─────────────────────────────────────────

class ApiKeyRequestCreate(BaseModel):
    purpose: str = Field(..., min_length=10, max_length=500)
    tier: ApiKeyTier = ApiKeyTier.FREE

class ApiKeyRequestResponse(BaseModel):
    request_id: str
    user_id: str
    email: str
    name: str
    purpose: str
    tier: str
    status: str
    created_at: datetime

class ApiKeyResponse(BaseModel):
    key_id: str
    user_id: str
    email: str
    key_prefix: str      # show this, not the raw key
    tier: str
    created_at: datetime
    expires_at: Optional[datetime]
    last_used_at: Optional[datetime]
    is_active: bool
    rate_limit_rpm: int

class ApiKeyIssuedResponse(BaseModel):
    key_id: str
    raw_api_key: str     # shown ONLY ONCE
    key_prefix: str
    tier: str
    rate_limit_rpm: int
    expires_at: Optional[datetime]
    message: str

class DocAccessGrant(BaseModel):
    doc_id: str
    access_level: DocAccessLevel
    expires_at: Optional[datetime] = None

class DocAccessResponse(BaseModel):
    permission_id: str
    user_id: str
    doc_id: str
    doc_title: str
    access_level: str
    granted_by: str
    granted_at: datetime
    expires_at: Optional[datetime]
    is_revoked: bool

# ─── User: Request API Key ───────────────────────────────────

@router.post("/user/api-key/request", response_model=dict)
async def request_api_key(
    body: ApiKeyRequestCreate,
    user: User = Depends(get_current_user),
):
    """
    User requests an API key.
    Goes to pending queue for admin approval.
    """
    neo4j = get_neo4j()
    request_id = f"akr_{uuid.uuid4().hex[:16]}"
    created_at = datetime.utcnow()

    with neo4j.session() as session:
        # Check existing pending request
        existing = session.run("""
            MATCH (u:User {user_id: $uid})-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {status: 'pending'})
            RETURN r.request_id as rid
        """, uid=user.user_id).single()

        if existing:
            raise HTTPException(status_code=400, detail="You already have a pending API key request")

        session.run("""
            MATCH (u:User {user_id: $uid})
            CREATE (r:ApiKeyRequest {
                request_id: $rid,
                purpose: $purpose,
                tier: $tier,
                status: 'pending',
                created_at: datetime($created_at)
            })
            CREATE (u)-[:REQUESTED_API_KEY]->(r)
        """, uid=user.user_id, rid=request_id,
            purpose=body.purpose, tier=body.tier.value,
            created_at=created_at.isoformat())

    return {
        "request_id": request_id,
        "status": "pending",
        "message": "API key request submitted. Awaiting admin approval.",
    }

@router.get("/user/api-key/my-requests", response_model=list[ApiKeyRequestResponse])
async def my_api_key_requests(user: User = Depends(get_current_user)):
    """User views their own API key requests"""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        results = list(session.run("""
            MATCH (u:User {user_id: $uid})-[:REQUESTED_API_KEY]->(r:ApiKeyRequest)
            RETURN r.request_id as request_id, r.purpose as purpose,
                   r.tier as tier, r.status as status, r.created_at as created_at,
                   u.email as email, u.name as name
            ORDER BY r.created_at DESC
        """, uid=user.user_id))

    return [
        ApiKeyRequestResponse(
            request_id=r["request_id"],
            user_id=user.user_id,
            email=r["email"],
            name=r["name"],
            purpose=r["purpose"],
            tier=r["tier"],
            status=r["status"],
            created_at=r["created_at"] or datetime.utcnow(),
        )
        for r in results
    ]

@router.get("/user/api-key/my-keys", response_model=list[ApiKeyResponse])
async def my_api_keys(user: User = Depends(get_current_user)):
    """User views their own issued API keys (not raw)"""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        results = list(session.run("""
            MATCH (u:User {user_id: $uid})-[:HAS_API_KEY]->(k:ApiKey)
            RETURN k.key_id as key_id, k.key_prefix as key_prefix,
                   k.tier as tier, k.created_at as created_at,
                   k.expires_at as expires_at, k.last_used_at as last_used_at,
                   k.is_active as is_active, k.rate_limit_rpm as rate_limit_rpm,
                   u.email as email
            ORDER BY k.created_at DESC
        """, uid=user.user_id))

    return [
        ApiKeyResponse(
            key_id=r["key_id"],
            user_id=user.user_id,
            email=r["email"],
            key_prefix=r["key_prefix"],
            tier=r["tier"],
            created_at=r["created_at"] or datetime.utcnow(),
            expires_at=r["expires_at"],
            last_used_at=r["last_used_at"],
            is_active=r["is_active"],
            rate_limit_rpm=r["rate_limit_rpm"] or 10,
        )
        for r in results
    ]

# ─── Admin: API Key Requests ────────────────────────────────

@router.get("/admin/api-key/requests", response_model=list[ApiKeyRequestResponse])
async def list_api_key_requests(
    status: Optional[str] = Query(None, description="pending/approved/rejected"),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """Admin: list API key requests"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        if status:
            results = list(session.run(f"""
                MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {{status: '$status'}})
                RETURN r.request_id as request_id, r.purpose as purpose,
                       r.tier as tier, r.status as status, r.created_at as created_at,
                       u.user_id as user_id, u.email as email, u.name as name
                ORDER BY r.created_at DESC LIMIT {limit}
            """.replace("$status", status)))
        else:
            results = list(session.run("""
                MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest)
                RETURN r.request_id as request_id, r.purpose as purpose,
                       r.tier as tier, r.status as status, r.created_at as created_at,
                       u.user_id as user_id, u.email as email, u.name as name
                ORDER BY r.created_at DESC LIMIT $limit
            """, limit=limit))

    return [
        ApiKeyRequestResponse(
            request_id=r["request_id"],
            user_id=r["user_id"],
            email=r["email"],
            name=r["name"],
            purpose=r["purpose"],
            tier=r["tier"],
            status=r["status"],
            created_at=r["created_at"] or datetime.utcnow(),
        )
        for r in results
    ]

@router.post("/admin/api-key/approve/{request_id}", response_model=ApiKeyIssuedResponse)
async def approve_api_key(request_id: str, user: User = Depends(get_current_user)):
    """
    Admin approves API key request.
    Returns the RAW API KEY — shown only this time.
    """
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    raw_key, key_prefix, key_hash = generate_api_key()
    key_id = f"ak_{uuid.uuid4().hex[:16]}"
    tier_str = None
    expires_days = 90

    with neo4j.session() as session:
        # Get request details
        req = session.run("""
            MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {request_id: $rid})
            RETURN r.tier as tier, u.user_id as uid, u.email as email
        """, rid=request_id).single()

        if not req:
            raise HTTPException(status_code=404, detail="Request not found")

        tier_str = req["tier"]
        tier = ApiKeyTier(tier_str)
        limits = RATE_LIMITS[tier]
        expires_at = datetime.utcnow() + timedelta(days=expires_days)

        # Update request + create API key node
        session.run("""
            MATCH (u:User {user_id: $uid})-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {request_id: $rid})
            SET r.status = 'approved', r.reviewed_by = $admin, r.reviewed_at = datetime()
            CREATE (k:ApiKey {
                key_id: $key_id, key_hash: $key_hash, key_prefix: $key_prefix,
                tier: $tier, created_at: datetime(), expires_at: datetime($exp_iso),
                is_active: true, rate_limit_rpm: $rpm, usage_count: 0,
                reviewed_by: $admin
            })
            CREATE (u)-[:HAS_API_KEY]->(k)
        """, uid=req["uid"], rid=request_id, admin=user.user_id,
            key_id=key_id, key_hash=key_hash, key_prefix=key_prefix,
            tier=tier_str, exp_iso=expires_at.isoformat(),
            rpm=limits["rpm"])

    return ApiKeyIssuedResponse(
        key_id=key_id,
        raw_api_key=raw_key,
        key_prefix=key_prefix,
        tier=tier_str,
        rate_limit_rpm=limits["rpm"],
        expires_at=expires_at,
        message="⚠️ Copy this API key now — it will not be shown again!",
    )

@router.post("/admin/api-key/reject/{request_id}")
async def reject_api_key(
    request_id: str,
    reason: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
):
    """Admin rejects API key request"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        n = session.run("""
            MATCH (u:User)-[:REQUESTED_API_KEY]->(r:ApiKeyRequest {request_id: $rid})
            SET r.status = 'rejected', r.reviewed_by = $admin,
                r.reviewed_at = datetime(), r.rejection_reason = $reason
        """, rid=request_id, admin=user.user_id, reason=reason)
        if n.consume().counters.nodes_set == 0:
            raise HTTPException(status_code=404, detail="Request not found")

    return {"request_id": request_id, "status": "rejected", "reason": reason}

@router.get("/admin/api-keys", response_model=list[ApiKeyResponse])
async def list_all_api_keys(
    user_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """Admin: list all issued API keys"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        if user_id:
            results = list(session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_API_KEY]->(k:ApiKey)
                RETURN k.key_id as key_id, k.key_prefix as key_prefix,
                       k.tier as tier, k.created_at as created_at,
                       k.expires_at as expires_at, k.last_used_at as last_used_at,
                       k.is_active as is_active, k.rate_limit_rpm as rate_limit_rpm,
                       u.email as email, u.user_id as user_id
                ORDER BY k.created_at DESC LIMIT $limit
            """, uid=user_id, limit=limit))
        else:
            results = list(session.run("""
                MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey)
                RETURN k.key_id as key_id, k.key_prefix as key_prefix,
                       k.tier as tier, k.created_at as created_at,
                       k.expires_at as expires_at, k.last_used_at as last_used_at,
                       k.is_active as is_active, k.rate_limit_rpm as rate_limit_rpm,
                       u.email as email, u.user_id as user_id
                ORDER BY k.created_at DESC LIMIT $limit
            """, limit=limit))

    return [
        ApiKeyResponse(
            key_id=r["key_id"],
            user_id=r["user_id"],
            email=r["email"],
            key_prefix=r["key_prefix"],
            tier=r["tier"],
            created_at=r["created_at"] or datetime.utcnow(),
            expires_at=r["expires_at"],
            last_used_at=r["last_used_at"],
            is_active=r["is_active"],
            rate_limit_rpm=r["rate_limit_rpm"] or 10,
        )
        for r in results
    ]

@router.delete("/admin/api-key/revoke/{key_id}")
async def revoke_api_key(
    key_id: str,
    reason: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
):
    """Admin revokes an API key"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        n = session.run("""
            MATCH (k:ApiKey {key_id: $kid})
            SET k.is_active = false, k.revoked_by = $admin,
                k.revoked_at = datetime(), k.revoked_reason = $reason
        """, kid=key_id, admin=user.user_id, reason=reason).consume()
        if n.nodes_set == 0:
            raise HTTPException(status_code=404, detail="Key not found")

    return {"key_id": key_id, "status": "revoked"}

# ─── Document Access ────────────────────────────────────────

@router.post("/admin/doc-access/grant")
async def grant_doc_access(
    body: DocAccessGrant,
    user_id: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
):
    """Admin grants document access to a user"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    perm_id = f"dap_{uuid.uuid4().hex[:16]}"

    with neo4j.session() as session:
        # Verify user and doc exist
        u = session.run("MATCH (u:User {user_id: $uid}) RETURN u.user_id", uid=user_id).single()
        d = session.run("MATCH (d:Document {doc_id: $did}) RETURN d.doc_id", did=body.doc_id).single()
        if not u or not d:
            raise HTTPException(status_code=404, detail="User or Document not found")

        session.run("""
            MATCH (u:User {user_id: $uid}), (d:Document {doc_id: $did})
            CREATE (p:UserDocPermission {
                permission_id: $pid, access_level: $level,
                granted_by: $admin, granted_at: datetime(),
                expires_at: $exp, is_revoked: false
            })
            CREATE (u)-[:HAS_DOC_ACCESS]->(p)-[:GRANTED_ON_DOCUMENT]->(d)
        """, uid=user_id, did=body.doc_id, pid=perm_id,
            level=body.access_level.value, admin=user.user_id,
            exp=body.expires_at.isoformat() if body.expires_at else None)

    return {"permission_id": perm_id, "status": "granted"}

@router.delete("/admin/doc-access/revoke/{permission_id}")
async def revoke_doc_access(
    permission_id: str,
    user: User = Depends(get_current_user),
):
    """Admin revokes document access"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        n = session.run("""
            MATCH (p:UserDocPermission {permission_id: $pid})
            SET p.is_revoked = true, p.revoked_at = datetime()
        """, pid=permission_id).consume()
        if n.nodes_set == 0:
            raise HTTPException(status_code=404, detail="Permission not found")

    return {"permission_id": permission_id, "status": "revoked"}

@router.get("/admin/doc-access/list")
async def list_doc_access(
    doc_id: Optional[str] = Query(None),
    target_user_id: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """Admin: list document access permissions"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")

    neo4j = get_neo4j()
    with neo4j.session() as session:
        if doc_id:
            results = list(session.run("""
                MATCH (u:User)-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document {doc_id: $did})
                RETURN p.permission_id as permission_id, u.user_id as user_id,
                       u.name as user_name, u.email as email,
                       d.doc_id as doc_id, d.title as doc_title,
                       p.access_level as access_level, p.granted_by as granted_by,
                       p.granted_at as granted_at, p.expires_at as expires_at,
                       p.is_revoked as is_revoked
                ORDER BY p.granted_at DESC LIMIT $limit
            """, did=doc_id, limit=limit))
        elif target_user_id:
            results = list(session.run("""
                MATCH (u:User {user_id: $uid})-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document)
                RETURN p.permission_id as permission_id, u.user_id as user_id,
                       u.name as user_name, u.email as email,
                       d.doc_id as doc_id, d.title as doc_title,
                       p.access_level as access_level, p.granted_by as granted_by,
                       p.granted_at as granted_at, p.expires_at as expires_at,
                       p.is_revoked as is_revoked
                ORDER BY p.granted_at DESC LIMIT $limit
            """, uid=target_user_id, limit=limit))
        else:
            results = list(session.run("""
                MATCH (u:User)-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document)
                RETURN p.permission_id as permission_id, u.user_id as user_id,
                       u.name as user_name, u.email as email,
                       d.doc_id as doc_id, d.title as doc_title,
                       p.access_level as access_level, p.granted_by as granted_by,
                       p.granted_at as granted_at, p.expires_at as expires_at,
                       p.is_revoked as is_revoked
                ORDER BY p.granted_at DESC LIMIT $limit
            """, limit=limit))

    return [
        DocAccessResponse(
            permission_id=r["permission_id"],
            user_id=r["user_id"],
            doc_id=r["doc_id"],
            doc_title=r.get("doc_title", r["doc_id"]),
            access_level=r["access_level"],
            granted_by=r["granted_by"],
            granted_at=r["granted_at"] or datetime.utcnow(),
            expires_at=r["expires_at"],
            is_revoked=r["is_revoked"],
        )
        for r in results
    ]

@router.get("/user/doc-access/my-access")
async def my_doc_access(user: User = Depends(get_current_user)):
    """User views their own document access permissions"""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        results = list(session.run("""
            MATCH (u:User {user_id: $uid})-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document)
            WHERE p.is_revoked = false
            RETURN p.permission_id as permission_id, p.access_level as access_level,
                   p.granted_by as granted_by, p.granted_at as granted_at,
                   p.expires_at as expires_at,
                   d.doc_id as doc_id, d.title as doc_title
            ORDER BY p.granted_at DESC
        """, uid=user.user_id))

    return [
        DocAccessResponse(
            permission_id=r["permission_id"],
            user_id=user.user_id,
            doc_id=r["doc_id"],
            doc_title=r.get("doc_title", r["doc_id"]),
            access_level=r["access_level"],
            granted_by=r["granted_by"],
            granted_at=r["granted_at"] or datetime.utcnow(),
            expires_at=r["expires_at"],
            is_revoked=False,
        )
        for r in results
    ]
