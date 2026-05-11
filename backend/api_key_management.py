"""
Legal GraphRAG — API Key Management
===================================
ระบบขอ API Key เพื่อใช้งาน as a Service
Flow: User request → Admin approve → API Key issued → User use API key

API Key vs JWT:
  - JWT: ใช้ภายใน app (login ผ่าน browser)
  - API Key: ใช้ external service / programmatic access
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from enum import Enum

# ─── Models ────────────────────────────────────────────────────────────────────

class ApiKeyStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    REVOKED = "revoked"
    EXPIRED = "expired"

class ApiKeyTier(str, Enum):
    FREE = "free"           # rate limited
    STANDARD = "standard"   # normal rate
    PREMIUM = "premium"     # high rate
    ENTERPRISE = "enterprise"

class ApiKeyRequest(BaseModel):
    """User's API key request"""
    request_id: str
    user_id: str
    email: str
    purpose: str                    # คำอธิบายวัตถุประสงค์การใช้งาน
    tier: ApiKeyTier = ApiKeyTier.FREE
    requested_at: datetime
    status: ApiKeyStatus = ApiKeyStatus.PENDING
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None

class ApiKey(BaseModel):
    """Issued API Key"""
    key_id: str
    user_id: str
    email: str
    key_hash: str                   # hashed API key (never store raw)
    key_prefix: str                  # first 8 chars for identification
    tier: ApiKeyTier
    created_at: datetime
    expires_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    is_active: bool = True
    rate_limit_rpm: int             # requests per minute
    usage_count: int = 0

# ─── Rate Limits by Tier ────────────────────────────────────────────────────────

RATE_LIMITS = {
    ApiKeyTier.FREE:       {"rpm": 10,  "rpm_window": 60,   "daily": 500,   "monthly": 5000},
    ApiKeyTier.STANDARD:   {"rpm": 60,  "rpm_window": 60,   "daily": 5000,  "monthly": 50000},
    ApiKeyTier.PREMIUM:    {"rpm": 300, "rpm_window": 60,  "daily": 50000, "monthly": 500000},
    ApiKeyTier.ENTERPRISE: {"rpm": 1000,"rpm_window": 60,  "daily": -1,    "monthly": -1},
}

# ─── Neo4j Schema Additions ─────────────────────────────────────────────────────

API_KEY_NODES_CYPHER = """
// API Key Request (pending/approved/rejected)
CREATE CONSTRAINT api_key_request_id IF NOT EXISTS
FOR (r:ApiKeyRequest) REQUIRE r.request_id IS UNIQUE;

// API Key (issued and active)
CREATE CONSTRAINT api_key_key_id IF NOT EXISTS
FOR (k:ApiKey) REQUIRE k.key_id IS UNIQUE;

// User has many API keys
CREATE (u:User)-[:REQUESTED]->(r:ApiKeyRequest)
CREATE (u:User)-[:HAS_API_KEY]->(k:ApiKey)
"""

# ─── Document Access Permission ─────────────────────────────────────────────────

class DocAccessLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    ADMIN = "admin"  # full control including delete/sharing

class UserDocPermission(BaseModel):
    """Per-user document access permission"""
    permission_id: str
    user_id: str
    doc_id: str
    access_level: DocAccessLevel
    granted_by: str          # admin who granted
    granted_at: datetime
    expires_at: Optional[datetime] = None
    is_revoked: bool = False

DOC_ACCESS_CYPHER = """
// User-Document access permission
CREATE CONSTRAINT user_doc_permission_id IF NOT EXISTS
FOR (p:UserDocPermission) REQUIRE p.permission_id IS UNIQUE;

CREATE (u:User)-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON]->(d:Document)
"""

# ─── Usage Tracking ─────────────────────────────────────────────────────────────

class ApiKeyUsage(BaseModel):
    """Track API key usage for billing/rate limiting"""
    usage_id: str
    key_id: str
    endpoint: str
    method: str
    status_code: int
    tokens_used: Optional[int] = None
    latency_ms: int
    timestamp: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

USAGE_CYPHER = """
CREATE (u:ApiKeyUsage)-[:USES_KEY]->(k:ApiKey)
CREATE (u:ApiKeyUsage)-[:CALLS_ENDPOINT]->(e:Endpoint)
"""

# ─── API Key Generation ────────────────────────────────────────────────────────

import hashlib
import secrets
import base64

def generate_api_key() -> tuple[str, str, str]:
    """
    Generate a new API key.
    Returns: (raw_key, key_prefix, key_hash)
    - raw_key: ให้ user 1 ครั้งเท่านั้น (ไม่เก็บ)
    - key_prefix: สำหรับแสดงใน list (e.g. "lgk_7f3b2c1d")
    - key_hash: เก็บใน DB เพื่อเช็คทุกครั้ง
    """
    raw = secrets.token_urlsafe(32)                    # 43 chars
    key_prefix = f"lgk_{raw[:8]}"
    key_hash = hashlib.sha256(raw.encode()).hexdigest()
    return raw, key_prefix, key_hash

def verify_api_key(raw_key: str, stored_hash: str) -> bool:
    """Verify an API key against its stored hash"""
    return hashlib.sha256(raw_key.encode()).hexdigest() == stored_hash

# ─── Neo4j Operations ────────────────────────────────────────────────────────────

def create_api_key_request(tx, request: ApiKeyRequest) -> None:
    tx.run("""
        MATCH (u:User {user_id: $user_id})
        CREATE (r:ApiKeyRequest $props)
        CREATE (u)-[:REQUESTED_API_KEY]->(r)
    """, user_id=request.user_id, props=request.model_dump())

def approve_api_key_request(tx, request_id: str, key: ApiKey, reviewer_id: str) -> str:
    """Approve request and issue API key. Returns the raw key (shown only once)."""
    raw_key, key_prefix, key_hash = generate_api_key()
    
    result = tx.run("""
        MATCH (req:ApiKeyRequest {request_id: $req_id})
        SET req.status = 'approved',
            req.reviewed_by = $reviewer,
            req.reviewed_at = datetime()
        
        WITH req
        MATCH (u:User {user_id: req.user_id})
        CREATE (k:ApiKey {
            key_id: $key.key_id,
            user_id: req.user_id,
            email: req.email,
            key_hash: $key_hash,
            key_prefix: $key_prefix,
            tier: req.tier,
            created_at: datetime(),
            expires_at: $expires_at,
            is_active: true,
            rate_limit_rpm: $rate_limit,
            usage_count: 0
        })
        CREATE (u)-[:HAS_API_KEY]->(k)
        RETURN k.key_id as key_id
    """, req_id=request_id, reviewer=reviewer_id, 
        key=key.model_dump(), key_hash=key_hash, key_prefix=key_prefix,
        expires_at=key.expires_at.isoformat() if key.expires_at else None,
        rate_limit=RATE_LIMITS[key.tier]["rpm"])
    return raw_key

def revoke_api_key(tx, key_id: str, revoked_by: str, reason: str) -> None:
    tx.run("""
        MATCH (k:ApiKey {key_id: $key_id})
        SET k.is_active = false,
            k.revoked_by = $revoked_by,
            k.revoked_reason = $reason,
            k.revoked_at = datetime()
    """, key_id=key_id, revoked_by=revoked_by, reason=reason)

# ─── Document Access Operations ────────────────────────────────────────────────

def grant_doc_access(tx, permission: UserDocPermission) -> None:
    tx.run("""
        MATCH (u:User {user_id: $user_id}), (d:Document {doc_id: $doc_id})
        CREATE (p:UserDocPermission $props)
        CREATE (u)-[:HAS_DOC_ACCESS]->(p)-[:GRANTED_ON_DOCUMENT]->(d)
    """, user_id=permission.user_id, 
        doc_id=permission.doc_id,
        props=permission.model_dump())

def revoke_doc_access(tx, permission_id: str) -> None:
    tx.run("""
        MATCH (p:UserDocPermission {permission_id: $pid})
        SET p.is_revoked = true, p.revoked_at = datetime()
    """, pid=permission_id)

def check_user_doc_access(tx, user_id: str, doc_id: str) -> Optional[str]:
    """
    Check if user has document access.
    Returns access_level or None.
    
    Check order (highest first):
    1. User-specific permission (UserDocPermission)
    2. Role-based permission (User.role.access_level on Document)
    3. Document default access level
    """
    result = tx.run("""
        // 1. Direct user permission
        MATCH (u:User {user_id: $uid})-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document {doc_id: $did})
        WHERE p.is_revoked = false AND (p.expires_at IS NULL OR p.expires_at > datetime())
        RETURN p.access_level as level, 1 as priority
        UNION
        // 2. Role-based (user's role == doc's allowed roles)
        MATCH (u:User {user_id: $uid})-[:HAS_ROLE]->(r:Role)-[:ALLOWS_ACCESS]->(d:Document {doc_id: $did})
        RETURN r.access_level as level, 2 as priority
        UNION
        // 3. Public documents
        MATCH (d:Document {doc_id: $did})
        WHERE d.access_level = 'public'
        RETURN 'read' as level, 3 as priority
        ORDER BY priority ASC
        LIMIT 1
    """, uid=user_id, did=doc_id)
    record = result.single()
    return record["level"] if record else None

def get_user_accessible_docs(tx, user_id: str) -> list[dict]:
    """Get all documents user has access to (for UI display)"""
    result = tx.run("""
        MATCH (u:User {user_id: $uid})
        OPTIONAL MATCH (u)-[:HAS_DOC_ACCESS]->(p:UserDocPermission)-[:GRANTED_ON_DOCUMENT]->(d:Document)
        WHERE p.is_revoked = false AND (p.expires_at IS NULL OR p.expires_at > datetime())
        WITH d, p, 1 as src
        OPTIONAL MATCH (u)-[:HAS_ROLE]->(r:Role)-[:ALLOWS_ACCESS]->(d2:Document)
        WHERE r.access_level IN ['read', 'write', 'admin']
        WITH collect(DISTINCT d) + collect(DISTINCT d2) as all_docs, src
        UNWIND all_docs as doc
        RETURN DISTINCT doc { .*, access_type: 'role_based' } as document
        LIMIT 100
    """, uid=user_id)
    return [dict(r["document"]) for r in result]
