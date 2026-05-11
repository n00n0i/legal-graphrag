"""
Legal GraphRAG — Project Summary
================================
📁 /root/hermes-law-graphrag/

Files:
  neo4j_schema.py      — Entity types + relationships (Law/Case/Common)
  qdrant_schema.py     — Collection configs + access filter
  llm_prompts.py       — LLM extraction prompts + output schemas
  document_parser.py   — PDF parsers (Law + General) + OCS fetcher
  entity_extractor.py  — LLM entity extraction + embedding
  ingestion.py         — Full pipeline: PDF → Parse → Extract → Store
  api.py               — FastAPI + RBAC middleware + endpoints

Quick Start:
  1. Init schema:
     python ingestion.py init-schema

  2. Ingest law PDF:
     python ingestion.py run /path/to/law.pdf [law_id]

  3. Run API:
     uvicorn api:app --host 0.0.0.0 --port 8000

  4. Test query:
     curl -X POST http://localhost:8000/api/v1/query \
       -H "Authorization: Bearer citizen_user123" \
       -H "Content-Type: application/json" \
       -d '{"question": "ผู้ขับขี่ประมาททำให้ผู้อื่นเสียชีวิต มีโทษอะไรบ้าง"}'

RBAC Roles:
  citizen  → PUBLIC only
  officer  → PUBLIC + INTERNAL
  lawyer   → PUBLIC + INTERNAL + REGULATED
  admin    → all levels

API Endpoints:
  POST /api/v1/query           — NLP Q&A
  GET  /api/v1/search         — Keyword search
  POST /api/v1/documents/upload — Upload document
  GET  /api/v1/admin/stats    — Admin stats
  GET  /health                — Health check

Tech Stack:
  Neo4j (graph) + Qdrant (vector) + GPT-4o (LLM) + BGE-M3 (embedder) + FastAPI

Status: Core pipeline ready. Frontend pending.
"""

# This file is just documentation — no executable code
pass