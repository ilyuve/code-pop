from sqlalchemy import text
from database import SessionLocal


def optimize_hnsw_index():
    """优化 HNSW 索引参数。"""
    db = SessionLocal()
    try:
        db.execute(text("DROP INDEX IF EXISTS idx_embedding_vector"))
        
        db.execute(text("""
            CREATE INDEX idx_embedding_vector ON embeddings 
            USING hnsw (embedding vector_cosine_ops) 
            WITH (m = 32, ef_construction = 128)
        """))
        
        db.commit()
        print("HNSW index optimized: m=32, ef_construction=128")
    finally:
        db.close()


if __name__ == "__main__":
    optimize_hnsw_index()
