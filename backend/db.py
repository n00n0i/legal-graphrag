"""
Legal GraphRAG — Shared dependencies (neo4j, auth)
Avoids circular imports between api.py and router modules.
"""
from functools import lru_cache
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"  # Local dev — overwritten by api.py settings at runtime
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "neo4j123"


@lru_cache(maxsize=1)
def get_neo4j_driver():
    """Returns a singleton Neo4j driver."""
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_neo4j():
    """Dependency — FastAPI injects via Depends(get_neo4j)."""
    return get_neo4j_driver()