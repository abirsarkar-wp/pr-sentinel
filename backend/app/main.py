import logging
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.ingestion import ingest_repo
from app.models import Repo
from app.retrieval import search_code
from app.webhooks import router as webhooks_router


logging.basicConfig(level=logging.INFO)


app = FastAPI(title="PR Sentinel API")

app.include_router(webhooks_router)


@app.get("/")
def read_root():
    return {
        "status": "ok",
        "service": "pr-sentinel-backend",
    }


@app.get("/health")
def health_check():
    return {"healthy": True}


@app.post("/repos/{repo_id}/ingest")
async def trigger_ingestion(
    repo_id: int,
    db: Session = Depends(get_db),
):
    repo = (
        db.query(Repo)
        .filter(Repo.id == repo_id)
        .first()
    )

    if repo is None:
        raise HTTPException(
            status_code=404,
            detail="Repo not found",
        )

    chunk_count = await ingest_repo(db, repo)

    repo.last_indexed_at = datetime.now(timezone.utc)

    db.commit()

    return {
        "repo": repo.full_name,
        "chunks_stored": chunk_count,
    }


@app.get("/repos/{repo_id}/search")
def search_repo(
    repo_id: int,
    q: str,
    db: Session = Depends(get_db),
):
    repo = (
        db.query(Repo)
        .filter(Repo.id == repo_id)
        .first()
    )

    if repo is None:
        raise HTTPException(
            status_code=404,
            detail="Repo not found",
        )

    results = search_code(
        db=db,
        repo_id=repo_id,
        query=q,
    )

    return {
        "query": q,
        "results": results,
    }