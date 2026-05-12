"""
Legal GraphRAG — Init Conversation Schema
Run: python3 init_conversations.py
"""
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7688"
NEO4J_USER = "neo4j"
NEO4J_PASSWORD = "neo4j123"

stmts = [
    "CREATE CONSTRAINT conversation_id IF NOT EXISTS FOR (c:Conversation) REQUIRE c.id IS UNIQUE",
    "CREATE CONSTRAINT message_id IF NOT EXISTS FOR (m:Message) REQUIRE m.id IS UNIQUE",
    "CREATE INDEX conversation_user IF NOT EXISTS FOR (c:Conversation) ON (c.user_id)",
    "CREATE INDEX conversation_updated IF NOT EXISTS FOR (c:Conversation) ON (c.updated_at)",
    "CREATE INDEX message_created IF NOT EXISTS FOR (m:Message) ON (m.created_at)",
]

def init():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    with driver.session() as session:
        for stmt in stmts:
            try:
                session.run(stmt)
                print(f"OK: {stmt[:60]}")
            except Exception as e:
                print(f"SKIP: {stmt[:60]} — {e}")
        print("Done!")
    driver.close()

if __name__ == '__main__':
    init()