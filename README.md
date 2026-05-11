# Legal GraphRAG

Thai Government Law Q&A System with GraphRAG + Dynamic RBAC.

## Structure

```
legal-graphrag/
├── backend/         — FastAPI + Neo4j + Qdrant (port 8000)
├── user-portal/     — User React app (port 3000)
└── admin-portal/    — Admin React app (port 3001)
```

## Quick Start

```bash
# Backend
cd backend && pip install -r requirements.txt
uvicorn api:app --host 0.0.0.0 --port 8000

# User Portal
cd user-portal && npm install && npm run dev

# Admin Portal
cd admin-portal && npm install && npm run dev
```

## Stack
- **Backend**: FastAPI, Neo4j, Qdrant, BGE-M3 embeddings, GPT-4o
- **Frontend**: React 18, Vite, Tailwind CSS, React Router
- **Auth**: JWT (Keycloak-compatible)
