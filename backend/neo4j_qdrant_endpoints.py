"""
Legal GraphRAG — Neo4j + Qdrant Admin Browse Endpoints
=======================================================
"""
from typing import Optional

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel

from api import get_neo4j, get_qdrant
from user_management import User

router = APIRouter(prefix="/api/v1", tags=["admin_browse"])


def get_current_user():
    """Lazy import to avoid circular dependency with api.py."""
    from api import get_current_user as gcu
    return gcu


def rbac_check(user: User, permission: str):
    if user.role_id == "admin":
        return
    raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")


# ─── Neo4j ───────────────────────────────────────────────────────────────────

@router.get("/neo4j/stats")
async def neo4j_stats(user: User = Depends(get_current_user)):
    rbac_check(user, "neo4j:read")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
        rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]
        labels = session.run("CALL db.labels()").fetch()
        label_counts = {}
        for row in labels:
            lbl = row["label"]
            cnt = session.run(f"MATCH (n:`{lbl}`) RETURN count(n) as cnt").single()["cnt"]
            label_counts[lbl] = cnt
    return {"nodes": node_count, "relationships": rel_count, "labels": label_counts}


@router.post("/neo4j/cypher")
async def run_cypher(
    query: str,
    user: User = Depends(get_current_user),
):
    rbac_check(user, "neo4j:write")
    neo4j = get_neo4j()
    with neo4j.session() as session:
        try:
            result = session.run(query).fetch()
            return {"columns": result[0].keys() if result else [], "rows": [dict(r) for r in result]}
        except Exception as e:
            raise HTTPException(status_code=400, detail=str(e))


# ─── Qdrant ───────────────────────────────────────────────────────────────────

@router.get("/qdrant/collections")
async def list_collections(user: User = Depends(get_current_user)):
    rbac_check(user, "qdrant:read")
    qdrant = get_qdrant()
    try:
        cols = qdrant.get_collections().collections
        return [{"name": c.name, "vectors_count": getattr(c, 'vectors_count', 0),
                 "points_count": getattr(c, 'points_count', 0)} for c in cols]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/collections/{name}/points")
async def get_collection_points(
    name: str,
    limit: int = Query(10, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
):
    rbac_check(user, "qdrant:read")
    qdrant = get_qdrant()
    try:
        scroll = qdrant.scroll(collection_name=name, limit=limit, offset=offset)
        points = scroll[0] if scroll else []
        return {
            "collection": name,
            "total": len(points),
            "points": [{"id": p.id, "vector": list(p.vector)[:5] if hasattr(p, 'vector') else [],
                        "payload": p.payload} for p in points],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qdrant/collections/{name}")
async def delete_collection(name: str, user: User = Depends(get_current_user)):
    rbac_check(user, "qdrant:delete")
    qdrant = get_qdrant()
    try:
        qdrant.delete_collection(collection_name=name)
        return {"ok": True, "collection": name}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))