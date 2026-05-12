"""
Legal GraphRAG — Main FastAPI Application
==========================================
Stack: FastAPI + Neo4j + Qdrant + GPT-4o + BGE-M3 embeddings

Usage:
  uvicorn api:app --host 0.0.0.0 --port 8000
"""

import os, time, uuid, hashlib, base64, secrets
from datetime import datetime, timedelta
from typing import Optional, Literal
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Query, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from dotenv import load_dotenv
import os as _os
_load_dotenv = load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
from neo4j import GraphDatabase
from qdrant_client import QdrantClient
import openai

from qdrant_schema import QDRANT_COLLECTIONS, qdrant_access_filter, EMBEDDER_CONFIG
from neo4j_schema import AccessLevel
from entity_extractor import Embedder, LawEntityExtractor
from user_management import (
    UserManager, RoleManager, PermissionManager, RBACChecker,
    init_rbac_schema, Permission, Role, User, PermissionCategory,
)


# ─── Config ──────────────────────────────────────────────────────────────────

class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7688"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j123"
    qdrant_url: str = "http://localhost:6335"
    qdrant_api_key: Optional[str] = None
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    jwt_secret: str = os.getenv("JWT_SECRET", "dev-secret-change-in-prod")
    jwt_algorithm: str = "HS256"
    jwt_expiry_hours: int = 24

model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

settings = Settings()


# ─── Auth Helpers ─────────────────────────────────────────────────────────────

def hash_api_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


def generate_api_key() -> str:
    return f"lg_{secrets.token_urlsafe(32)}"


def create_jwt(user_id: str, role: str) -> str:
    import jwt
    payload = {
        "sub": user_id, "role": role,
        "exp": datetime.utcnow() + timedelta(hours=settings.jwt_expiry_hours),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_jwt(token: str) -> dict:
    import jwt
    try:
        return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ─── Current User Dependency ──────────────────────────────────────────────────

async def get_current_user(authorization: Optional[str] = Header(None)) -> User:
    """
    Unified auth: JWT Bearer token OR API key (lgk_xxx).
    Returns User object with user_id, email, name, role_id, status.
    """
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
            user_id=payload["sub"], email="",
            name="", role_id=payload.get("role", "citizen"),
            status="active",
        )
    except HTTPException:
        pass
    except Exception:
        pass

    # Try API key
    if token.startswith("lgk_"):
        key_hash = hash_api_key(token)
        try:
            driver = get_neo4j()
            with driver.session() as session:
                result = session.run("""
                    MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey {key_hash: $hash, is_active: true})
                    WHERE k.expires_at IS NULL OR k.expires_at > datetime()
                    RETURN u.user_id as uid, u.email as email, u.name as name,
                           u.role_id as role, k.tier as tier, k.rate_limit_rpm as rpm
                    LIMIT 1
                """, hash=key_hash).single()
                if result:
                    session.run("""
                        MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey {key_hash: $hash})
                        SET k.last_used_at = datetime()
                    """, hash=key_hash)
                    return User(
                        user_id=result["uid"], email=result["email"] or "",
                        name=result["name"] or "", role_id=result["role"],
                        status="active",
                    )
        except Exception:
            pass
        raise HTTPException(status_code=401, detail="Invalid or expired API key")

    raise HTTPException(status_code=401, detail="Invalid token")


# ─── DB ──────────────────────────────────────────────────────────────────────

_neo4j_driver = None
_qdrant_client = None


def get_neo4j():
    global _neo4j_driver
    if _neo4j_driver is None:
        _neo4j_driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )
    return _neo4j_driver


def get_qdrant():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=settings.qdrant_url, api_key=settings.qdrant_api_key)
    return _qdrant_client


# ─── Pydantic Models ─────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    user_id: str; email: str; name: str; role_id: str; status: str


class QueryRequest(BaseModel):
    question: str
    collection: Optional[str] = "legal_default"
    limit: Optional[int] = 5
    conversation_id: Optional[str] = None


# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    neo4j = get_neo4j()
    with neo4j.session() as session:
        try:
            init_rbac_schema(session)
        except Exception:
            pass
    yield
    global _neo4j_driver
    if _neo4j_driver:
        _neo4j_driver.close()
        _neo4j_driver = None


app = FastAPI(title="Legal GraphRAG API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)


# ─── Conversations ───────────────────────────────────────────────────────────

@app.get("/api/v1/conversations")
async def list_conversations(
    limit: int = Query(20, le=100),
    user: User = Depends(get_current_user),
):
    """List user's conversation threads."""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (c:Conversation {user_id: $uid})
            RETURN c.id as id, c.title as title, c.created_at as ca, c.updated_at as ua
            ORDER BY c.updated_at DESC
            LIMIT $limit
        """, uid=user.user_id, limit=limit).data()
    return [
        {"id": r["id"], "title": r["title"], "created_at": str(r["ca"]), "updated_at": str(r["ua"])}
        for r in result
    ]


@app.post("/api/v1/conversations")
async def create_conversation(
    body: Optional[dict] = Body(None),
    user: User = Depends(get_current_user),
):
    """Create a new conversation thread."""
    neo4j = get_neo4j()
    conv_id = str(uuid.uuid4())
    title = (body or {}).get("title") or "New conversation"
    with neo4j.session() as session:
        session.run("""
            CREATE (c:Conversation {
                id: $id, user_id: $uid, title: $title,
                created_at: datetime(), updated_at: datetime()
            })
        """, id=conv_id, uid=user.user_id, title=title)
    return {"id": conv_id, "title": title}


@app.get("/api/v1/conversations/{conv_id}")
async def get_conversation(
    conv_id: str,
    user: User = Depends(get_current_user),
):
    """Get a conversation by ID."""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        r = session.run("""
            MATCH (c:Conversation {id: $cid, user_id: $uid})
            RETURN c.id as id, c.title as title, c.created_at as ca, c.updated_at as ua
        """, cid=conv_id, uid=user.user_id).single()
        if not r:
            raise HTTPException(status_code=404, detail="Not found")
    return {"id": r["id"], "title": r["title"], "created_at": str(r["ca"]), "updated_at": str(r["ua"])}


@app.get("/api/v1/conversations/{conv_id}/messages")
async def get_conversation_messages(
    conv_id: str,
    limit: int = Query(50, le=200),
    user: User = Depends(get_current_user),
):
    """Get messages in a conversation."""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        result = session.run("""
            MATCH (c:Conversation {id: $cid, user_id: $uid})-[:HAS_MESSAGE]->(m:Message)
            RETURN m.id as id, m.role as role, m.content as content, m.created_at as ca
            ORDER BY m.created_at ASC
            LIMIT $limit
        """, cid=conv_id, uid=user.user_id, limit=limit).data()
    return [
        {"id": r["id"], "role": r["role"], "content": r["content"],
         "created_at": str(r["ca"]) if r["ca"] else None}
        for r in result
    ]


@app.patch("/api/v1/conversations/{conv_id}")
async def update_conversation(
    conv_id: str,
    title: str = Body(...),
    user: User = Depends(get_current_user),
):
    """Update conversation title."""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        r = session.run("""
            MATCH (c:Conversation {id: $cid, user_id: $uid})
            SET c.title = $title, c.updated_at = datetime()
            RETURN c.id as id
        """, cid=conv_id, uid=user.user_id, title=title).single()
        if not r:
            raise HTTPException(status_code=404, detail="Not found")
    return {"id": conv_id, "title": title}


@app.delete("/api/v1/conversations/{conv_id}")
async def delete_conversation(
    conv_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a conversation."""
    neo4j = get_neo4j()
    with neo4j.session() as session:
        r = session.run("""
            MATCH (c:Conversation {id: $cid, user_id: $uid})
            DETACH DELETE c
            RETURN count(c) as cnt
        """, cid=conv_id, uid=user.user_id).single()
        if not r or r["cnt"] == 0:
            raise HTTPException(status_code=404, detail="Not found")
    return {"ok": True}


# ─── Query / RAG ─────────────────────────────────────────────────────────────

@app.post("/api/v1/query")
async def query(req: QueryRequest, user: User = Depends(get_current_user)):
    """Non-streaming RAG query."""
    from openai_anthropic_compat import run_pipeline
    conv_id = req.conversation_id
    messages = []
    if conv_id:
        neo4j = get_neo4j()
        with neo4j.session() as session:
            hist = session.run("""
                MATCH (c:Conversation {id: $cid, user_id: $uid})-[:HAS_MESSAGE]->(m:Message)
                RETURN m.role as role, m.content as content ORDER BY m.created_at ASC
            """, cid=conv_id, uid=user.user_id).data()
            if hist:
                messages = [{"role": r["role"], "content": r["content"]} for r in hist]
    messages.append({"role": "user", "content": req.question})
    try:
        answer = await run_pipeline(req.question, user, req.limit or 5, messages)
    except Exception as e:
        answer = f"Error: {e}"
    if conv_id and answer:
        neo4j = get_neo4j()
        try:
            with neo4j.session() as session:
                uid2 = str(uuid.uuid4()); aid2 = str(uuid.uuid4())
                session.run("""
                    MATCH (c:Conversation {id: $cid})
                    CREATE (c)-[:HAS_MESSAGE]->(um:Message {id: $uid, role: 'user', content: $qc, created_at: datetime()})
                    CREATE (c)-[:HAS_MESSAGE]->(am:Message {id: $aid, role: 'assistant', content: $ac, created_at: datetime()})
                    SET c.updated_at = datetime()
                """, cid=conv_id, uid=uid2, qc=req.question, aid=aid2, ac=answer)
        except Exception:
            pass
    return {"answer": answer, "sources": [], "conversation_id": conv_id}


@app.post("/api/v1/query/stream")
async def query_stream(req: QueryRequest, user: User = Depends(get_current_user)):
    """Streaming RAG query via SSE."""
    from fastapi.responses import StreamingResponse
    from openai_anthropic_compat import synthesis_stream, run_pipeline
    conv_id = req.conversation_id
    messages = []
    if conv_id:
        neo4j = get_neo4j()
        with neo4j.session() as session:
            hist = session.run("""
                MATCH (c:Conversation {id: $cid, user_id: $uid})-[:HAS_MESSAGE]->(m:Message)
                RETURN m.role as role, m.content as content ORDER BY m.created_at ASC
            """, cid=conv_id, uid=user.user_id).data()
            if hist:
                messages = [{"role": r["role"], "content": r["content"]} for r in hist]
    messages.append({"role": "user", "content": req.question})

    async def event_stream():
        full = ""
        try:
            async for token in synthesis_stream(user, req.question, "context_placeholder",
                                                "gpt-4o", 0.3, 1024, "openai"):
                full += token
                yield f"data: {token}\n\n"
            yield "event: done\ndata: [DONE]\n\n"
        except Exception as e:
            yield f"event: error\ndata: {e}\n\n"
        if conv_id and full:
            neo4j = get_neo4j()
            try:
                with neo4j.session() as session:
                    uid2 = str(uuid.uuid4()); aid2 = str(uuid.uuid4())
                    session.run("""
                        MATCH (c:Conversation {id: $cid})
                        CREATE (c)-[:HAS_MESSAGE]->(um:Message {id: $uid, role: 'user', content: $qc, created_at: datetime()})
                        CREATE (c)-[:HAS_MESSAGE]->(am:Message {id: $aid, role: 'assistant', content: $ac, created_at: datetime()})
                        SET c.updated_at = datetime()
                    """, cid=conv_id, uid=uid2, qc=req.question, aid=aid2, ac=full)
            except Exception:
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ─── Auth Endpoints ────────────────────────────────────────────────────────────

_neo4j_driver_local = None

class _SessionWrapper:
    """Wraps a neo4j Driver to provide .execute() for UserManager compatibility."""
    def __init__(self, driver):
        self._driver = driver

    def execute(self, query, params=None):
        with self._driver.session() as session:
            result = session.run(query, params or {})
            return result.data()

    def execute_write(self, query, params=None):
        with self._driver.session() as session:
            return session.run(query, params or {}).data()

    def close(self):
        self._driver.close()


def _get_driver():
    global _neo4j_driver_local
    if _neo4j_driver_local is None:
        _neo4j_driver_local = GraphDatabase.driver(
            "bolt://localhost:7688", auth=("neo4j", "neo4j123"))
    return _SessionWrapper(_neo4j_driver_local)


@app.post("/api/v1/auth/register")
async def register(
    email: str = Body(...),
    name: str = Body(...),
    password: str = Body(...),
):
    # Hash password and store it on the User node
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    mgr = UserManager(_get_driver())
    try:
        user = mgr.register(email=email, name=name, requested_role="citizen")
        # Now update password hash
        mgr.db.execute_write(
            "MATCH (u:User {user_id: $uid}) SET u.password_hash = $pw",
            {"uid": user.user_id, "pw": password_hash}
        )
        return {"user_id": user.user_id, "email": user.email, "name": user.name, "role_id": user.role_id, "status": "pending"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/v1/auth/login")
async def login(
    email: str = Body(...),
    password: str = Body(...),
):
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    mgr = UserManager(_get_driver())
    # Find user by email + password hash
    result = mgr.db.execute(
        "MATCH (u:User {email: $email, password_hash: $pw}) RETURN u.user_id as uid, u.email as email, u.name as name, u.role_id as role, u.status as status",
        {"email": email, "pw": password_hash}
    )
    if not result:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_data = result[0]
    user = User(
        user_id=user_data["uid"], email=user_data["email"],
        name=user_data["name"], role_id=user_data["role"],
        status=user_data["status"],
    )
    token = create_jwt(user.user_id, user.role_id)
    return {
        "token": token,
        "user": {
            "user_id": user.user_id, "email": user.email, "name": user.name,
            "role_id": user.role_id, "status": user.status,
        },
    }


@app.get("/api/v1/auth/me")
async def me(user: User = Depends(get_current_user)):
    return {
        "user_id": user.user_id, "email": user.email, "name": user.name,
        "role_id": user.role_id, "status": user.status,
    }


# ─── Admin ───────────────────────────────────────────────────────────────────

@app.get("/api/v1/admin/stats")
async def admin_stats(user: User = Depends(get_current_user)):
    if user.role_id != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        nodes = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
        rels = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        users = session.run("MATCH (u:User) RETURN count(u) as c").single()["c"]
        docs = session.run("MATCH (d:Document) RETURN count(d) as c").single()["c"]
    return {"nodes": nodes, "relationships": rels, "users": users, "documents": docs}


# ─── Routers (lazy-load to avoid circular imports) ────────────────────────────

def _include_routers():
    """Called after app is fully constructed to avoid circular import at import time."""
    from api_key_endpoints import router as api_key_router
    from openai_anthropic_compat import router as compat_router
    from document_endpoints import router as doc_router
    from neo4j_qdrant_endpoints import router as admin_browse_router

    app.include_router(api_key_router)
    app.include_router(compat_router)
    app.include_router(doc_router)
    app.include_router(admin_browse_router)


# Include routers now (after all endpoints defined)
_include_routers()


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "legal-graphrag"}