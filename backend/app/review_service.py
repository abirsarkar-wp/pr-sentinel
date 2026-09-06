from sqlalchemy.orm import Session

from app.agent import run_agent_review
from app.github_api import get_pr, get_pr_files
from app.models import AgentTrace, Finding, PullRequest, Review


async def run_review_for_pr(
    db: Session,
    pr: PullRequest,
) -> Review:
    repo = pr.repo

    pr_data = await get_pr(
        repo,
        pr.github_pr_number,
    )

    files = await get_pr_files(
        repo,
        pr.github_pr_number,
    )

    (
        final,
        draft,
        traces,
        tokens_used,
        turns_taken,
    ) = await run_agent_review(
        db,
        repo,
        pr_data,
        files,
    )

    review = Review(
        pr_id=pr.id,
        status="completed",
        summary=final.summary,
        tokens_used=tokens_used,
        turns_taken=turns_taken,
    )

    db.add(review)
    db.commit()
    db.refresh(review)

    for finding in final.findings:
        db.add(
            Finding(
                review_id=review.id,
                file=finding.file,
                line_start=finding.line_start,
                line_end=finding.line_end,
                category=finding.category,
                severity=finding.severity,
                explanation=finding.explanation,
                suggested_fix=finding.suggested_fix,
                confidence=finding.confidence,
            )
        )

    for trace in traces:
        db.add(
            AgentTrace(
                review_id=review.id,
                turn_number=trace["turn"],
                role=trace["role"],
                content_json=trace["content"],
                tool_calls_json=None,
                latency_ms=trace.get("latency_ms"),
            )
        )

    db.commit()

    return review