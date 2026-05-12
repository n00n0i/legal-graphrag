"""
Legal GraphRAG — OpenAI + Anthropic Compatible Endpoints
==========================================================
Supports:
  - OpenAI /v1/chat/completions  (messages, model, stream, etc.)
  - Anthropic /v1/messages       (messages, model, stream, etc.)

Both proxy to the same GraphRAG pipeline:
  1. Embed question via OpenAI-compatible embedder
  2. Search Qdrant with RBAC-filtered vector search
  3. Synthesize answer via LLM (OpenAI or Anthropic)

Streaming via text/event-stream (SSE).
"""

import os, time, uuid, asyncio
from typing import Optional, AsyncGenerator, Literal
from datetime import datetime

from fastapi import APIRouter, HTTPException, Depends, Header, Query, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import openai
from anthropic import AsyncAnthropic

from api import get_current_user as _gcu, User as _UserCls, get_qdrant as _gq, settings as _settings, EMBEDDER_CONFIG as _EC, Embedder as _EmbedderCls
get_current_user = _gcu; User = _UserCls; get_qdrant = _gq; settings = _settings; EMBEDDER_CONFIG = _EC; Embedder = _EmbedderCls

router = APIRouter(prefix="/v1", tags=["openai_compat", "anthropic_compat"])

# ─── Shared Pipeline Helpers ──────────────────────────────────────

def build_citations(results: list) -> tuple[list, str]:
    """Build citation list + context string from Qdrant results."""
    citations = []
    context_chunks = []
    for i, r in enumerate(results):
        section_id = r.payload.get("source_section_id", "")
        law_title = r.payload.get("law_title", "")
        excerpt = str(r.payload.get("chunk_text", r.payload))[:400]
        citations.append({
            "index": i + 1,
            "section_id": section_id,
            "law_title": law_title,
            "excerpt": excerpt,
            "score": r.score,
        })
        context_chunks.append(f"[{i+1}] {law_title}: {excerpt}")
    context = "\n\n".join(context_chunks[:5])
    return citations, context


def synthesis_stream(user: User, question: str, context: str,
                     model: str, temperature: float, max_tokens: int,
                     provider: str = "openai") -> AsyncGenerator[str, None]:
    """
    Yield SSE chunks for streaming synthesis.
    provider: "openai" | "anthropic"
    """
    system_prompt = """คุณเป็นที่ปรึกษากฎหมายไทย
ผู้ใช้: {role}
ตอบคำถามโดยอ้างอิงมาตราที่เกี่ยวข้อง กระชับ พร้อมอ้างอิงมาตรา
หากไม่แน่ใจ ให้บอกว่าไม่ทราบ ไม่สร้างข้อมูลเท็จ"""

    user_content = f"""คำถาม: {question}

ข้อมูลที่ค้นพบ:
{context}

ตอบเป็นภาษาไทย กระชับ อ้างอิงมาตรา"""

    if provider == "anthropic":
        # Anthropic streaming
        anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key or settings.openai_api_key)
        system_msg = {"role": "system", "content": system_prompt}
        user_msg = {"role": "user", "content": user_content}

        async def stream_anthropic():
            try:
                async with anthropic.messages.stream(
                    model=model or "claude-sonnet-4-6.20251113",
                    max_tokens=max_tokens or 1000,
                    temperature=temperature or 0.3,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                ) as stream:
                    async for text_event in stream.aiter_text():
                        # SSE format
                        delta = {"choices": [{"delta": {"content": text_event}}]}
                        yield f"data: {delta}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"

        return stream_anthropic()

    else:
        # OpenAI streaming
        openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        system_msg = {"role": "system", "content": system_prompt}

        async def stream_openai():
            try:
                stream = openai_client.chat.completions.create(
                    model=model or "gpt-4o",
                    messages=[system_msg, {"role": "user", "content": user_content}],
                    temperature=temperature or 0.3,
                    max_tokens=max_tokens or 1000,
                    stream=True,
                )
                for chunk in stream:
                    delta = {"choices": [{"delta": {"content": chunk.choices[0].delta.content or ""}}]}
                    yield f"data: {delta}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"

        return stream_openai()


async def synthesis_nonstream(user: User, question: str, context: str,
                               model: str, temperature: float, max_tokens: int,
                               provider: str = "openai") -> str:
    """Non-streaming synthesis."""
    system_prompt = """คุณเป็นที่ปรึกษากฎหมายไทย ตอบกระชับ อ้างอิงมาตรา"""

    user_content = f"""คำถาม: {question}

ข้อมูลที่ค้นพบ:
{context}

ตอบเป็นภาษาไทย กระชับ อ้างอิงมาตรา"""

    if provider == "anthropic":
        anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key or settings.openai_api_key)
        try:
            resp = await anthropic.messages.create(
                model=model or "claude-sonnet-4-6.20251113",
                max_tokens=max_tokens or 1000,
                temperature=temperature or 0.3,
                system=system_prompt,
                messages=[{"role": "user", "content": user_content}],
            )
            return resp.content[0].text
        except Exception as e:
            return f"(Anthropic LLM unavailable: {e})\n\nข้อมูลที่พบ: {context[:500]}"

    else:
        openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        try:
            resp = openai_client.chat.completions.create(
                model=model or "gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature or 0.3,
                max_tokens=max_tokens or 1000,
                stream=False,
            )
            return resp.choices[0].message.content
        except Exception as e:
            return f"(LLM unavailable: {e})\n\nข้อมูลที่พบ: {context[:500]}"


def run_pipeline(question: str, user: User, limit: int = 10):
    """
    Run the shared GraphRAG pipeline:
      1. Embed question
      2. Search Qdrant (RBAC filtered)
      3. Return (results, citations, context)
    """
    embedder = Embedder(
        provider="openai",
        api_key=settings.openai_api_key,
        dimension=EMBEDDER_CONFIG["dimension"],
    )
    question_vector = embedder.embed(question)

    qdrant = get_qdrant()
    allowed_levels = qdrant_access_filter(user.role_id)

    from qdrant_client.models import Filter, FieldCondition, MatchAny

    results = qdrant.search(
        collection_name="law_chunks",
        query_vector=question_vector,
        query_filter=Filter(must=[
            FieldCondition(key="access_level", match=MatchAny(any=allowed_levels))
        ]),
        limit=limit,
    )

    citations, context = build_citations(results)
    return results, citations, context


# ─── OpenAI-Compatible Chat Completions ────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = "user"
    content: str
    name: Optional[str] = None

class ChatCompletionsRequest(BaseModel):
    model: str = "gpt-4o"
    messages: list[ChatMessage]
    temperature: Optional[float] = 0.3
    max_tokens: Optional[int] = 1000
    stream: Optional[bool] = False
    user: Optional[str] = None  # OpenAI compat: ignores extra fields


@router.post("/chat/completions")
async def chat_completions(
    body: ChatCompletionsRequest,
    authorization: Optional[str] = Header(None),
):
    """
    OpenAI-compatible /v1/chat/completions endpoint.
    Supports streaming (text/event-stream).

    Auth: Bearer <JWT> or Bearer <lgk_API_KEY>
    """
    # Auth via API key or JWT
    token = _extract_bearer(authorization)
    user = _authenticate(token)

    # Extract last user message as the question
    question = _extract_last_user_message(body.messages)
    if not question:
        raise HTTPException(status_code=400, detail="No user message found")

    # Run pipeline
    _, citations, context = run_pipeline(question, user)

    if body.stream:
        return StreamingResponse(
            _stream_sse(question, context, body.model,
                       body.temperature, body.max_tokens, "openai"),
            media_type="text/event-stream",
        )

    # Non-streaming
    answer = await synthesis_nonstream(
        user, question, context,
        model=body.model, temperature=body.temperature,
        max_tokens=body.max_tokens, provider="openai",
    )

    return {
        "id": f"chatcmpl_{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(datetime.utcnow().timestamp()),
        "model": body.model,
        "choices": [{
            "index": 0,
            "message": {
                "role": "assistant",
                "content": answer,
            },
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": len(question),
            "completion_tokens": len(answer),
            "total_tokens": len(question) + len(answer),
        },
    }


# ─── Anthropic-Compatible Messages ──────────────────────────────────────────

class AnthropicMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str

class AnthropicMessagesRequest(BaseModel):
    model: str = "claude-sonnet-4-6.20251113"
    messages: list[AnthropicMessage]
    max_tokens: Optional[int] = 1024
    temperature: Optional[float] = 0.3
    stream: Optional[bool] = False
    system: Optional[str] = None  # Anthropic system prompt


@router.post("/messages")
async def anthropic_messages(
    body: AnthropicMessagesRequest,
    authorization: Optional[str] = Header(None),
):
    """
    Anthropic-compatible /v1/messages endpoint.
    Supports streaming (text/event-stream).

    Auth: Bearer <JWT> or Bearer <lgk_API_KEY>
    """
    token = _extract_bearer(authorization)
    user = _authenticate(token)

    # Extract last user message
    question = ""
    for msg in reversed(body.messages):
        if msg.role == "user":
            question = msg.content
            break
    if not question:
        raise HTTPException(status_code=400, detail="No user message found")

    # Inject system prompt override if provided
    system_override = body.system

    _, citations, context = run_pipeline(question, user)

    if body.stream:
        return StreamingResponse(
            _stream_sse(question, context, body.model,
                       body.temperature, body.max_tokens, "anthropic",
                       system_override),
            media_type="text/event-stream",
        )

    # Non-streaming
    answer = await synthesis_nonstream(
        user, question, context,
        model=body.model, temperature=body.temperature,
        max_tokens=body.max_tokens, provider="anthropic",
    )

    return {
        "id": f"msg_{uuid.uuid4().hex[:12]}",
        "type": "message",
        "role": "assistant",
        "content": [{
            "type": "text",
            "text": answer,
        }],
        "model": body.model,
        "usage": {
            "input_tokens": len(question),
            "output_tokens": len(answer),
        },
    }


# ─── Auth Helpers ──────────────────────────────────────────────────────────

def _extract_bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def _extract_last_user_message(messages: list) -> str:
    """Pull the content string from the last user message."""
    for msg in reversed(messages):
        if isinstance(msg, dict):
            r = msg.get("role", "")
        elif hasattr(msg, "role"):
            r = msg.role
        else:
            continue
        if r == "user":
            return msg.get("content", "") if isinstance(msg, dict) else (msg.content or "")
    return ""


def _authenticate(token: Optional[str]) -> User:
    """
    Auth via lgk_ API key or JWT.
    Raises HTTPException 401 on failure.
    """
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    # Try JWT first (get_current_user looks up from DB)
    from api import hash_api_key; get_current_user = _get_current_user
    try:
        # If token starts with lgk_ it's an API key
        if token.startswith("lgk_"):
            get_neo4j = lambda: None  # filled in openai_compat.py
            key_hash = hash_api_key(token)
            driver = get_neo4j()
            with driver.session() as session:
                result = session.run("""
                    MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey {key_hash: $hash, is_active: true})
                    WHERE k.expires_at IS NULL OR k.expires_at > datetime()
                    RETURN u.user_id as uid, u.email as email, u.name as name,
                           u.role_id as role, k.tier as tier, k.rate_limit_rpm as rpm
                    LIMIT 1
                """, hash=key_hash).single()
                if not result:
                    raise HTTPException(status_code=401, detail="Invalid or inactive API key")
                session.run("MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey {key_hash: $hash}) SET k.last_used_at = datetime()",
                    hash=key_hash)
                return User(
                    user_id=result["uid"], email=result["email"] or "",
                    name=result["name"] or "", role_id=result["role"], status="active",
                )
        else:
            # Try JWT decode
            from user_management import user_mgr
            payload = user_mgr._decode_token(token)
            if payload:
                uid = payload.get("sub") or payload.get("user_id")
                if uid:
                    return User(
                        user_id=uid,
                        email=payload.get("email", ""),
                        name=payload.get("name", ""),
                        role_id=payload.get("role", "user"),
                        status="active",
                    )
    except HTTPException:
        raise
    except Exception:
        pass

    raise HTTPException(status_code=401, detail="Invalid token")


# ─── SSE Streaming Helper ──────────────────────────────────────────────────

async def _stream_sse(question: str, context: str,
                     model: str, temperature: Optional[float],
                     max_tokens: Optional[int],
                     provider: str,
                     system_override: Optional[str] = None
                     ) -> AsyncGenerator[str, None]:

    system_prompt = system_override or """คุณเป็นที่ปรึกษากฎหมายไทย
ตอบคำถามโดยอ้างอิงมาตราที่เกี่ยวข้อง กระชับ พร้อมอ้างอิงมาตรา"""

    user_content = f"""คำถาม: {question}

ข้อมูลที่ค้นพบ:
{context}

ตอบเป็นภาษาไทย กระชับ อ้างอิงมาตรา"""

    if provider == "anthropic":
        anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key or settings.openai_api_key)
        async def stream_anthropic():
            try:
                async with anthropic.messages.stream(
                    model=model or "claude-sonnet-4-6.20251113",
                    max_tokens=max_tokens or 1024,
                    temperature=temperature or 0.3,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_content}],
                ) as stream:
                    async for text_event in stream.aiter_text():
                        delta = {"choices": [{"delta": {"content": text_event}}]}
                        yield f"data: {delta}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"
        return stream_anthropic()

    else:
        openai_client = openai.OpenAI(api_key=settings.openai_api_key)
        async def stream_openai():
            try:
                stream = openai_client.chat.completions.create(
                    model=model or "gpt-4o",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temperature or 0.3,
                    max_tokens=max_tokens or 1024,
                    stream=True,
                )
                for chunk in stream:
                    delta = {"choices": [{"delta": {"content": chunk.choices[0].delta.content or ""}}]}
                    yield f"data: {delta}\n\n"
                yield "data: [DONE]\n\n"
            except Exception as e:
                yield f"data: [ERROR] {e}\n\n"
        return stream_openai()
