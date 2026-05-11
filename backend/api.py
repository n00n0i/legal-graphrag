"""
Legal GraphRAG — FastAPI Service with RBAC
==========================================
API Gateway + Query Engine + RBAC Middleware + User Management

Auth Flow:
  POST /api/v1/auth/register → pending → Admin approves → active
  POST /api/v1/auth/login    → JWT token
  POST /api/v1/auth/api-key  → API key (for service-to-service)

RBAC:
  Dynamic roles — admin สร้าง role ใหม่ได้เอง
  Admin approves user registration

Usage:
  uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os
import time
import uuid
import hashlib
import base64
import secrets
from datetime import datetime, timedelta
from typing import Optional, Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, EmailStr
from pydantic_settings import BaseSettings

from neo4j import GraphDatabase
from qdrant_client import QdrantClient
import openai

from qdrant_schema import QDRANT_COLLECTIONS, qdrant_access_filter, EMBEDDER_CONFIG
from neo4j_schema import AccessLevel
from entity_extractor import Embedder, LawEntityExtractor
from user_management import (
    UserManager, RoleManager, PermissionManager, RBACChecker,
    init_rbac_schema, SYSTEM_PERMISSIONS, SYSTEM_ROLES,
    Permission, Role, User,
    PermissionCategory,
)


# ─── Config ──────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j123"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: Optional[str] = None
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    embedder_base_url: Optional[str] = None
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

    class Config:
        env_file = ".env"


settings = Settings()


# ─── Auth Helpers ─────────────────────────────────────────────────────────────

def hash_api_key(key: str) -> str:
    """Hash API key for storage"""
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    """Generate new API key"""
    return f"lg_{secrets.token_urlsafe(32)}"


def create_jwt(user_id: str, role: str) -> str:
    """Create JWT token"""
    import jwt
    payload = {
        "sub": user_id,
        "role": role,
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expiry_hours),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    """Decode JWT token"""
    import jwt
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_user_from_token(authorization: str = None) -> User:
    """Extract user from Authorization header"""
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing authorization header")

    if authorization.startswith("Bearer "):
        token = authorization[7:]
    else:
        token = authorization

    # Try JWT
    try:
        payload = decode_jwt(token)
        return User(
            user_id=payload["sub"],
            email="",
            name="",
            role_id=payload.get("role", "citizen"),
            status="active",
        )
    except HTTPException:
        pass

    # Try API key format: lg_xxx
    if token.startswith("lg_"):
        # Look up user by API key hash
        key_hash = hash_api_key(token)
        # This would be checked against DB
        # For now, treat as service key with admin role
        return User(
            user_id="service",
            email="service@system",
            name="Service Account",
            role_id="admin",
            status="active",
        )

    raise HTTPException(status_code=401, detail="Invalid token")


async def get_current_user(authorization: Header(None)) -> User:
    try:
        return get_user_from_token(authorization)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=401, detail=str(e))


# ─── RBAC Dependency ──────────────────────────────────────────────────────────

async def require_permission(permission_id: str, user: User = Depends(get_current_user)):
    """Dependency — require specific permission"""
    # For now, check via role
    admin_roles = ["admin"]
    if user.role_id in admin_roles:
        return user
    
    # TODO: check permission via RBACChecker
    # perm_checker = RBACChecker(neo4j_driver)
    # if not perm_checker.has_permission(user.user_id, permission_id):
    #     raise HTTPException(status_code=403, detail=f"Missing permission: {permission_id}")
    
    return user


# ─── DB Connections ───────────────────────────────────────────────────────────

neo4j_driver = None
qdrant_client = None


def get_neo4j():
    global neo4j_driver
    if neo4j_driver is None:
        neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password)
        )
    return neo4j_driver


def get_qdrant():
    global qdrant_client
    if qdrant_client is None:
        qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return qdrant_client


def get_user_manager() -> UserManager:
    return UserManager(get_neo4j())


def get_role_manager() -> RoleManager:
    return RoleManager(get_neo4j())


def get_permission_manager() -> PermissionManager:
    return PermissionManager(get_neo4j())


# ─── Pydantic Models ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    email: str = Field(..., min_length=5)
    name: str = Field(..., min_length=1, max_length=200)
    requested_role: str = Field(default="citizen")


class LoginRequest(BaseModel):
    email: str
    api_key: Optional[str] = None


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


class UserResponse(BaseModel):
    user_id: str
    email: str
    name: str
    role_id: str
    status: str
    registered_at: Optional[datetime] = None
    approved_by: Optional[str] = None


class PendingUserResponse(BaseModel):
    user_id: str
    email: str
    name: str
    requested_role: str
    registered_at: datetime


class ApproveRequest(BaseModel):
    assigned_role: Optional[str] = None  # override requested role


class RejectRequest(BaseModel):
    reason: str = Field(default="")


class CreateRoleRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    display_name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    permissions: list[str] = []


class UpdateRoleRequest(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    permissions: Optional[list[str]] = None


class AssignRoleRequest(BaseModel):
    user_id: str
    role_id: str


# ─── FastAPI App ─────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[API] Starting Legal GraphRAG Service...")
    print(f"  Neo4j: {settings.neo4j_uri}")
    print(f"  Qdrant: {settings.qdrant_url}")
    yield
    print("[API] Shutting down...")


app = FastAPI(title="Legal GraphRAG API", version="0.2.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Lazy-initialize drivers
_user_mgr = None
_role_mgr = None
_perm_mgr = None


def user_mgr():
    global _user_mgr
    if _user_mgr is None:
        _user_mgr = UserManager(get_neo4j())
    return _user_mgr


def role_mgr():
    global _role_mgr
    if _role_mgr is None:
        _role_mgr = RoleManager(get_neo4j())
    return _role_mgr


def perm_mgr():
    global _perm_mgr
    if _perm_mgr is None:
        _perm_mgr = PermissionManager(get_neo4j())
    return _perm_mgr


# ─── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat(), "version": "0.2.0"}


# ─── Auth Endpoints ───────────────────────────────────────────────────────────

@app.post("/api/v1/auth/register", response_model=dict)
async def register(request: RegisterRequest):
    """
    ลงทะเบียนผู้ใช้ใหม่ — ได้สถานะ pending
    ต้องรอ admin approve ก่อนถึงจะ login ได้
    """
    try:
        u = user_mgr().register(
            email=request.email,
            name=request.name,
            requested_role=request.requested_role,
        )
        return {
            "user_id": u.user_id,
            "status": u.status,
            "message": "Registration submitted. Awaiting admin approval.",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/auth/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """
    Login — ใช้ email + password หรือ API key
    เฉพาะ user ที่ status=active เท่านั้นที่ login ได้
    """
    if request.api_key:
        # API key login
        key_hash = hash_api_key(request.api_key)
        # TODO: lookup by API key hash
        return LoginResponse(
            access_token="service_token_placeholder",
            user_id="service",
            role="admin",
        )
    
    # Email lookup (simplified — real app needs password hash)
    query = """
    MATCH (u:User {email: $email})
    WHERE u.status = 'active'
    RETURN u.user_id as uid, u.role_id as role
    """
    results = list(get_neo4j().execute(query, {"email": request.email}))
    
    if not results:
        raise HTTPException(status_code=401, detail="Invalid credentials or account not approved")
    
    r = results[0]
    token = create_jwt(r["uid"], r["role"])
    
    return LoginResponse(
        access_token=token,
        user_id=r["uid"],
        role=r["role"],
    )


@app.get("/api/v1/auth/me", response_model=UserResponse)
async def get_me(user: User = Depends(get_current_user)):
    """ดูข้อมูลตัวเอง"""
    try:
        u = user_mgr().get_user(user.user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(
            user_id=u.user_id,
            email=u.email,
            name=u.name,
            role_id=u.role_id,
            status=u.status,
            registered_at=u.registered_at,
        )
    except HTTPException:
        raise
    except Exception as e:
        return UserResponse(
            user_id=user.user_id,
            email=user.email or "unknown",
            name=user.name or "Unknown",
            role_id=user.role_id,
            status="active",
        )


# ─── Admin: User Management ───────────────────────────────────────────────────

@app.get("/api/v1/admin/users", response_model=list[UserResponse])
async def list_users(
    status: Optional[str] = Query(None, description="Filter by status: pending, active, rejected, suspended"),
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """list ผู้ใช้ทั้งหมด — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    users = user_mgr().list_users(status_filter=status, limit=limit)
    return [
        UserResponse(
            user_id=u.user_id,
            email=u.email,
            name=u.name,
            role_id=u.role_id,
            status=u.status,
            registered_at=u.registered_at,
        )
        for u in users
    ]


@app.get("/api/v1/admin/access-requests", response_model=list[PendingUserResponse])
async def list_pending_users(
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """list ผู้ใช้ที่รออนุมัติ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    pending = user_mgr().list_pending(limit=limit)
    
    # Get requested_role from neo4j
    results = list(get_neo4j().execute(
        """
        MATCH (u:User {status: 'pending'})
        RETURN u.user_id as uid, u.email as email, u.name as name,
               u.requested_role as requested_role, u.registered_at as registered_at
        ORDER BY u.registered_at DESC
        LIMIT $limit
        """,
        {"limit": limit}
    ))
    
    return [
        PendingUserResponse(
            user_id=r["uid"],
            email=r["email"],
            name=r["name"],
            requested_role=r.get("requested_role", "citizen"),
            registered_at=r["registered_at"],
        )
        for r in results
    ]


@app.post("/api/v1/admin/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    request: ApproveRequest = Body(...),
    user: User = Depends(get_current_user),
):
    """อนุมัติผู้ใช้ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        # Use assigned role if provided, otherwise keep requested role
        approved_user = user_mgr().approve(user_id, user.user_id)
        
        if request.assigned_role and request.assigned_role != approved_user.role_id:
            user_mgr().assign_role(user_id, request.assigned_role, user.user_id)
        
        return {
            "user_id": user_id,
            "status": "active",
            "message": f"User approved by {user.user_id}",
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/admin/users/{user_id}/reject")
async def reject_user(
    user_id: str,
    request: RejectRequest = Body(...),
    user: User = Depends(get_current_user),
):
    """ปฏิเสธผู้ใช้ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        user_mgr().reject(user_id, user.user_id, request.reason)
        return {"user_id": user_id, "status": "rejected", "reason": request.reason}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/admin/users/{user_id}/suspend")
async def suspend_user(
    user_id: str,
    reason: str = Body(..., embed=True),
    user: User = Depends(get_current_user),
):
    """ระงับผู้ใช้ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        user_mgr().suspend(user_id, user.user_id, reason)
        return {"user_id": user_id, "status": "suspended"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@app.post("/api/v1/admin/users/{target_user_id}/assign-role")
async def assign_role(
    target_user_id: str,
    request: AssignRoleRequest,
    user: User = Depends(get_current_user),
):
    """มอบหมาย role ให้ผู้ใช้ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        user_mgr().assign_role(target_user_id, request.role_id, user.user_id)
        return {"user_id": target_user_id, "role_id": request.role_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Role Management ─────────────────────────────────────────────────────────

@app.get("/api/v1/roles", response_model=list[dict])
async def list_roles(user: User = Depends(get_current_user)):
    """list roles ทั้งหมด — ทุกคนดูได้"""
    roles = role_mgr().list_roles()
    return [
        {
            "role_id": r.role_id,
            "name": r.name,
            "display_name": r.display_name,
            "description": r.description,
            "permissions": r.permissions,
            "is_system": r.is_system,
        }
        for r in roles
    ]


@app.post("/api/v1/roles")
async def create_role(
    request: CreateRoleRequest,
    user: User = Depends(get_current_user),
):
    """สร้าง role ใหม่ — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        new_role = role_mgr().create_role(
            name=request.name,
            display_name=request.display_name,
            permissions=request.permissions,
            description=request.description,
            created_by=user.user_id,
        )
        return {
            "role_id": new_role.role_id,
            "name": new_role.name,
            "display_name": new_role.display_name,
            "permissions": new_role.permissions,
            "message": "Role created successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.put("/api/v1/roles/{role_id}")
async def update_role(
    role_id: str,
    request: UpdateRoleRequest,
    user: User = Depends(get_current_user),
):
    """แก้ไข role — admin only (ไม่ใช่ system role)"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        updated = role_mgr().update_role(
            role_id=role_id,
            display_name=request.display_name,
            permissions=request.permissions,
            description=request.description,
        )
        return {
            "role_id": updated.role_id,
            "display_name": updated.display_name,
            "permissions": updated.permissions,
            "message": "Role updated successfully",
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.delete("/api/v1/roles/{role_id}")
async def delete_role(
    role_id: str,
    user: User = Depends(get_current_user),
):
    """ลบ role — admin only (ไม่ใช่ system role)"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        role_mgr().delete_role(role_id)
        return {"message": f"Role {role_id} deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Permissions ──────────────────────────────────────────────────────────────

@app.get("/api/v1/permissions", response_model=list[dict])
async def list_permissions(
    category: Optional[str] = Query(None),
    user: User = Depends(get_current_user),
):
    """list permissions ทั้งหมด — ทุกคนดูได้"""
    perm_cat = PermissionCategory(category) if category else None
    perms = perm_mgr().list_permissions(category=perm_cat)
    return [
        {
            "permission_id": p.permission_id,
            "name": p.name,
            "description": p.description,
            "category": p.category.value,
        }
        for p in perms
    ]


# ─── Query Endpoint (existing) ─────────────────────────────────────────────────

@app.post("/api/v1/query")
async def query(request: dict, user: User = Depends(get_current_user)):
    """NLP Q&A — ถามคำถามกฎหมาย"""
    start = time.time()
    question = request.get("question", "")
    
    if not question:
        raise HTTPException(status_code=400, detail="question is required")
    
    embedder = Embedder(
        provider="openai",
        api_key=settings.openai_api_key,
        dimension=EMBEDDER_CONFIG["dimension"],
    )
    
    try:
        question_vector = embedder.embed(question)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Embedding failed: {e}")
    
    # Search Qdrant
    qdrant = get_qdrant()
    allowed_levels = qdrant_access_filter(user.role_id)
    
    from qdrant_client.models import Filter, FieldCondition, MatchAny
    
    results = qdrant.search(
        collection_name="law_chunks",
        query_vector=question_vector,
        query_filter=Filter(must=[
            FieldCondition(key="access_level", match=MatchAny(any=allowed_levels))
        ]),
        limit=10,
    )
    
    citations = []
    sources = []
    for r in results:
        citations.append({
            "section_id": r.payload.get("source_section_id", ""),
            "law_title": r.payload.get("law_title", ""),
            "excerpt": str(r.payload)[:300],
            "score": r.score,
        })
        sources.append(f"law:{r.payload.get('source_law_id', '')}")
    
    # Build context
    context_chunks = "\n\n".join([
        f"[{i+1}] {c['law_title']}: {c['excerpt'][:300]}"
        for i, c in enumerate(citations[:5])
    ])
    
    # LLM Synthesis
    synthesis_prompt = f"""คุณเป็นที่ปรึกษากฎหมายไทย
ผู้ใช้: {user.role_id}
คำถาม: {question}

ข้อมูลที่ค้นพบ:
{context_chunks}

ตอบคำถามโดยอ้างอิงมาตราที่เกี่ยวข้อง ตอบเป็นภาษาไทย กระชับ พร้อมอ้างอิงมาตรา"""

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "คุณเป็นที่ปรึกษากฎหมายไทย ตอบกระชับ อ้างอิงมาตรา"},
                {"role": "user", "content": synthesis_prompt}
            ],
            temperature=0.3,
            max_tokens=1000,
        )
        answer = response.choices[0].message.content
    except Exception as e:
        answer = f"(LLM unavailable: {e})\n\nข้อมูลที่พบ: {context_chunks[:500]}"
    
    latency = (time.time() - start) * 1000
    
    return {
        "answer": answer,
        "citations": citations,
        "sources": list(set(sources)),
        "latency_ms": round(latency, 1),
    }


# ─── Admin Stats ──────────────────────────────────────────────────────────────

@app.get("/api/v1/admin/stats")
async def admin_stats(user: User = Depends(get_current_user)):
    """Dashboard stats — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    neo4j = get_neo4j()
    stats = {}
    
    with neo4j.session() as session:
        for label in ["Law", "Section", "Penalty", "User", "Role"]:
            result = session.run(f"MATCH (n:{label}) RETURN count(n) as cnt")
            stats[label.lower()] = dict(result.single())["cnt"]
        
        # Pending users
        result = session.run("MATCH (u:User {status: 'pending'}) RETURN count(u) as cnt")
        stats["pending_users"] = dict(result.single())["cnt"]
    
    return {"stats": stats, "timestamp": datetime.utcnow().isoformat()}


# ─── Init RBAC Schema ──────────────────────────────────────────────────────────

@app.post("/api/v1/admin/init-rbac")
async def init_rbac(user: User = Depends(get_current_user)):
    """Initialize RBAC schema — call once on first setup — admin only"""
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    
    try:
        init_rbac_schema(get_neo4j())
        return {"message": "RBAC schema initialized successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)