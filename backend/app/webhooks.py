import hmac
import hashlib
import json
import logging
from datetime import datetime, timezone
from app.ingestion import ingest_repo
from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Header,
    HTTPException,
    Request,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, SessionLocal
from app.models import PullRequest, Repo
from app.review_service import run_review_for_pr


logger = logging.getLogger("pr_sentinel.webhooks")

router = APIRouter()


def verify_signature(
    payload_body: bytes,
    signature_header: str | None,
) -> None:
    if not signature_header:
        raise HTTPException(
            status_code=401,
            detail="Missing X-Hub-Signature-256 header",
        )

    expected_signature = "sha256=" + hmac.new(
        key=settings.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        msg=payload_body,
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(
        expected_signature,
        signature_header,
    ):
        raise HTTPException(
            status_code=401,
            detail="Invalid signature",
        )


def get_or_create_repo(
    db: Session,
    payload: dict,
) -> Repo:
    repo_data = payload["repository"]
    installation_id = payload["installation"]["id"]

    repo = (
        db.query(Repo)
        .filter(
            Repo.github_repo_id == repo_data["id"]
        )
        .first()
    )

    if repo is None:
        repo = Repo(
            github_repo_id=repo_data["id"],
            full_name=repo_data["full_name"],
            installation_id=installation_id,
        )

        db.add(repo)
        db.commit()
        db.refresh(repo)

        logger.info(
            f"Created new repo record: {repo.full_name}"
        )

    else:
        repo.full_name = repo_data["full_name"]
        repo.installation_id = installation_id
        db.commit()
        db.refresh(repo)

    return repo


def upsert_pull_request(
    db: Session,
    repo: Repo,
    payload: dict,
) -> PullRequest:
    pr_data = payload["pull_request"]

    pr = (
        db.query(PullRequest)
        .filter(
            PullRequest.repo_id == repo.id,
            PullRequest.github_pr_number
            == pr_data["number"],
        )
        .first()
    )

    if pr is None:
        pr = PullRequest(
            repo_id=repo.id,
            github_pr_number=pr_data["number"],
            title=pr_data["title"],
            author=pr_data["user"]["login"],
            status=pr_data["state"],
        )

        db.add(pr)

        logger.info(
            f"Created new PR record: "
            f"#{pr.github_pr_number} {pr.title}"
        )

    else:
        pr.title = pr_data["title"]
        pr.status = pr_data["state"]

        logger.info(
            f"Updated existing PR record: "
            f"#{pr.github_pr_number}"
        )

    db.commit()
    db.refresh(pr)

    return pr


async def _run_review_in_background(
    pr_id: int,
):
    """
    Run the review using a new database session.

    If the repository has never been indexed, ingest it first.
    The request-scoped session may already be closed
    when this background task executes.
    """
    db = SessionLocal()

    try:
        pr = (
            db.query(PullRequest)
            .filter(PullRequest.id == pr_id)
            .first()
        )

        if pr is None:
            logger.error(
                f"Background review: PR id={pr_id} not found"
            )
            return

        repo = pr.repo

        # ---------------------------------------------------------
        # AUTOMATIC FIRST-TIME INDEXING
        # ---------------------------------------------------------
        if repo.last_indexed_at is None:
            logger.info(
                f"Repo {repo.full_name} never indexed "
                f"— ingesting before first review."
            )

            await ingest_repo(
                db,
                repo,
            )

            repo.last_indexed_at = datetime.now(
                timezone.utc
            )

            db.commit()

            logger.info(
                f"Finished initial indexing for "
                f"{repo.full_name}"
            )

        # ---------------------------------------------------------
        # RUN AI REVIEW
        # ---------------------------------------------------------
        logger.info(
            f"Starting background review for PR id={pr_id}"
        )

        await run_review_for_pr(
            db,
            pr,
        )

        logger.info(
            f"Finished background review for PR id={pr_id}"
        )

    except Exception as exc:
        logger.exception(
            f"Background review failed for "
            f"PR id={pr_id}: {exc}"
        )

    finally:
        db.close()


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    verify_signature(
        raw_body,
        x_hub_signature_256,
    )

    payload = json.loads(raw_body)

    logger.info(
        f"Received GitHub event: {x_github_event}"
    )

    if x_github_event == "pull_request":
        action = payload.get("action")

        if action in (
            "opened",
            "synchronize",
            "reopened",
        ):
            repo = get_or_create_repo(
                db,
                payload,
            )

            pr = upsert_pull_request(
                db,
                repo,
                payload,
            )

            logger.info(
                f"Persisted repo_id={repo.id}, "
                f"pr_id={pr.id}, action={action} "
                f"— queuing review."
            )

            background_tasks.add_task(
                _run_review_in_background,
                pr.id,
            )

    return {
        "received": True
    }
