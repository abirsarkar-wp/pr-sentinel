from sqlalchemy import select
from sqlalchemy.orm import Session

from app.embeddings import embed_query
from app.models import CodeChunk


def search_code(
    db: Session,
    repo_id: int,
    query: str,
    top_k: int = 5,
) -> list[dict]:
    """Return the most relevant code chunks using cosine similarity."""

    query_embedding = embed_query(query)

    distance = CodeChunk.embedding.cosine_distance(
        query_embedding
    ).label("distance")

    stmt = (
        select(CodeChunk, distance)
        .where(CodeChunk.repo_id == repo_id)
        .order_by(distance)
        .limit(top_k)
    )

    results = db.execute(stmt).all()

    return [
        {
            "file_path": chunk.file_path,
            "start_line": chunk.start_line,
            "end_line": chunk.end_line,
            "content": chunk.content,
            "similarity": 1 - dist,
        }
        for chunk, dist in results
    ]