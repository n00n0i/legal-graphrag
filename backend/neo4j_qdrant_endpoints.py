"""
Legal GraphRAG — Neo4j + Qdrant Admin Endpoints
===============================================
Admin-only: graph stats, cypher query, qdrant browse
"""

from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from neo4j import GraphDatabase

from api import get_current_user, User, get_neo4j, get_qdrant
from user_management import rbac_check

router = APIRouter(prefix="/api/v1/admin", tags=["admin", "neo4j", "qdrant"])

# ─── Neo4j ──────────────────────────────────────────────────

class CypherRequest(BaseModel):
    query: str
    limit: Optional[int] = 100


@router.get("/neo4j/stats")
async def neo4j_stats(user: User = Depends(get_current_user)):
    """Get Neo4j graph stats: node count, rel count, labels."""
    rbac_check(user, "neo4j:read")

    neo4j = get_neo4j()
    try:
        with neo4j.session() as session:
            # Node + rel counts
            node_count = session.run("MATCH (n) RETURN count(n) as count").single()["count"]
            rel_count = session.run("MATCH ()-[r]->() RETURN count(r) as count").single()["count"]

            # Label breakdown
            label_result = session.run("""
                MATCH (n)
                UNWIND labels(n) as label
                RETURN label, count(n) as count
                ORDER BY count DESC
                LIMIT 50
            """)
            labels = [{"label": r["label"], "count": r["count"]} for r in label_result]

            return {
                "total_nodes": node_count,
                "total_relationships": rel_count,
                "labels": labels,
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/neo4j/cypher")
async def neo4j_cypher(
    body: CypherRequest,
    user: User = Depends(get_current_user),
):
    """Run arbitrary Cypher query. Admin only."""
    rbac_check(user, "neo4j:write")

    # Disallow dangerous commands
    disallowed = ["DROP", "DELETE", "REMOVE", "DETACH"]
    for kw in disallowed:
        # Allow SELECT-like read but flag mutation
        if kw in body.query.upper() and body.query.strip().upper().startswith(kw):
            raise HTTPException(status_code=400, detail=f"Forbidden keyword: {kw}")

    neo4j = get_neo4j()
    try:
        with neo4j.session() as session:
            result = session.run(body.query, limit=body.limit)
            records = [dict(r) for r in result]
            return {
                "columns": list(result.keys()) if records else [],
                "data": records,
                "count": len(records),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ─── Qdrant ──────────────────────────────────────────────────

@router.get("/qdrant/collections")
async def qdrant_collections(user: User = Depends(get_current_user)):
    """List all Qdrant collections with stats."""
    rbac_check(user, "qdrant:read")

    qdrant = get_qdrant()
    try:
        cols = qdrant.get_collections()
        result = []
        for c in cols.collections:
            info = qdrant.get_collection(c.name)
            result.append({
                "name": c.name,
                "points_count": info.points_count,
                "vectors_count": info.vectors_count,
                "status": info.status,
            })
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/qdrant/collections/{collection}/points")
async def qdrant_points(
    collection: str,
    limit: int = 20,
    offset: int = 0,
    user: User = Depends(get_current_user),
):
    """Browse points in a collection."""
    rbac_check(user, "qdrant:read")

    qdrant = get_qdrant()
    try:
        results = qdrant.scroll(
            collection_name=collection,
            limit=limit,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        points = []
        for pid, payload in zip(results[0], results[1]):
            # Qdrant scroll returns (ids, payloads, vectors, offset)
            # Handle both formats
            if isinstance(pid, tuple):
                points.append({"id": str(pid[0]), "payload": pid[1] if len(pid) > 1 else {}})
            else:
                points.append({"id": str(pid), "payload": payload if isinstance(payload, dict) else {}})

        from qdrant_client.models import ScrollResponse
        if isinstance(results, ScrollResponse):
            return results.points

        return points
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qdrant/collections/{collection}")
async def qdrant_delete_collection(
    collection: str,
    user: User = Depends(get_current_user),
):
    """Delete a collection. Admin only."""
    rbac_check(user, "qdrant:write")

    qdrant = get_qdrant()
    try:
        qdrant.delete_collection(collection_name=collection)
        return {"collection": collection, "status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/qdrant/points/{collection}/{point_id}")
async def qdrant_delete_point(
    collection: str,
    point_id: str,
    user: User = Depends(get_current_user),
):
    """Delete a specific point. Admin only."""
    rbac_check(user, "qdrant:write")

    qdrant = get_qdrant()
    try:
        from qdrant_client.models import Filter, FieldCondition, MatchValue
        qdrant.delete(
            collection_name=collection,
            points_selector={
                "filter": Filter(must=[
                    FieldCondition(key="id", match=MatchValue(value=point_id))
                ])
            }
        )
        return {"point_id": point_id, "status": "deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
