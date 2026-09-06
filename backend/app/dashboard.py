from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import (
    AgentTrace,
    Finding,
    PullRequest,
    Repo,
    Review,
)


router = APIRouter()


@router.get("/repos")
def list_repos(
    db: Session = Depends(get_db),
):
    repos = db.query(Repo).all()

    result = []

    for repo in repos:
        review_count = (
            db.query(Review)
            .join(
                PullRequest,
                Review.pr_id == PullRequest.id,
            )
            .filter(
                PullRequest.repo_id == repo.id
            )
            .count()
        )

        result.append(
            {
                "id": repo.id,
                "full_name": repo.full_name,
                "connected_at": (
                    repo.connected_at.isoformat()
                    if repo.connected_at
                    else None
                ),
                "last_indexed_at": (
                    repo.last_indexed_at.isoformat()
                    if repo.last_indexed_at
                    else None
                ),
                "review_count": review_count,
            }
        )

    return result


@router.get("/repos/{repo_id}/pulls")
def list_pulls(
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

    prs = (
        db.query(PullRequest)
        .filter(
            PullRequest.repo_id == repo_id
        )
        .order_by(PullRequest.id.desc())
        .all()
    )

    result = []

    for pr in prs:
        latest_review = (
            db.query(Review)
            .filter(Review.pr_id == pr.id)
            .order_by(Review.id.desc())
            .first()
        )

        result.append(
            {
                "id": pr.id,
                "github_pr_number": pr.github_pr_number,
                "title": pr.title,
                "author": pr.author,
                "status": pr.status,
                "latest_review": (
                    {
                        "id": latest_review.id,
                        "status": latest_review.status,
                        "summary": latest_review.summary,
                        "tokens_used": latest_review.tokens_used,
                        "turns_taken": latest_review.turns_taken,
                    }
                    if latest_review
                    else None
                ),
            }
        )

    return {
        "repo": {
            "id": repo.id,
            "full_name": repo.full_name,
        },
        "pulls": result,
    }


@router.get("/reviews/{review_id}")
def get_review(
    review_id: int,
    db: Session = Depends(get_db),
):
    review = (
        db.query(Review)
        .filter(Review.id == review_id)
        .first()
    )

    if review is None:
        raise HTTPException(
            status_code=404,
            detail="Review not found",
        )

    findings = (
        db.query(Finding)
        .filter(
            Finding.review_id == review.id
        )
        .all()
    )

    pr = review.pull_request

    return {
        "id": review.id,
        "status": review.status,
        "summary": review.summary,
        "tokens_used": review.tokens_used,
        "turns_taken": review.turns_taken,
        "created_at": (
            review.created_at.isoformat()
            if review.created_at
            else None
        ),
        "pull_request": {
            "id": pr.id,
            "github_pr_number": pr.github_pr_number,
            "title": pr.title,
            "author": pr.author,
        },
        "findings": [
            {
                "id": finding.id,
                "file": finding.file,
                "line_start": finding.line_start,
                "line_end": finding.line_end,
                "category": finding.category,
                "severity": finding.severity,
                "explanation": finding.explanation,
                "suggested_fix": finding.suggested_fix,
                "confidence": finding.confidence,
            }
            for finding in findings
        ],
    }


@router.get("/reviews/{review_id}/traces")
def get_traces(
    review_id: int,
    db: Session = Depends(get_db),
):
    traces = (
        db.query(AgentTrace)
        .filter(
            AgentTrace.review_id == review_id
        )
        .order_by(
            AgentTrace.turn_number
        )
        .all()
    )

    return [
        {
            "turn_number": trace.turn_number,
            "role": trace.role,
            "content_json": trace.content_json,
            "latency_ms": trace.latency_ms,
            "created_at": (
                trace.created_at.isoformat()
                if trace.created_at
                else None
            ),
        }
        for trace in traces
    ]