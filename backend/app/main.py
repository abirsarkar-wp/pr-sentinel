import logging
from datetime import datetime, timezone
from app.dashboard import router as dashboard_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session
from app.review_service import run_review_for_pr
from app.database import get_db
from app.ingestion import ingest_repo
from app.models import Finding, PullRequest, Repo
from app.retrieval import search_code
from app.webhooks import router as webhooks_router


logging.basicConfig(level=logging.INFO)


app = FastAPI(title="PR Sentinel API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(webhooks_router)
app.include_router(dashboard_router)

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

@app.post("/reviews/run/{pr_id}")
async def trigger_review(
    pr_id: int,
    db: Session = Depends(get_db),
):
    pr = (
        db.query(PullRequest)
        .filter(PullRequest.id == pr_id)
        .first()
    )

    if pr is None:
        raise HTTPException(
            status_code=404,
            detail="PR not found",
        )

    review = await run_review_for_pr(
        db,
        pr,
    )

    findings = (
        db.query(Finding)
        .filter(Finding.review_id == review.id)
        .all()
    )

    return {
        "review_id": review.id,
        "summary": review.summary,
        "tokens_used": review.tokens_used,
        "turns_taken": review.turns_taken,
        "findings_count": len(findings),
        "findings": [
            {
                "file": finding.file,
                "lines": (
                    f"{finding.line_start}-"
                    f"{finding.line_end}"
                ),
                "category": finding.category,
                "severity": finding.severity,
                "explanation": finding.explanation,
                "confidence": finding.confidence,
            }
            for finding in findings
        ],
    }