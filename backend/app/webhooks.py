import hmac
import hashlib
import json
import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.models import PullRequest, Repo


logger = logging.getLogger("pr_sentinel.webhooks")

router = APIRouter()


def verify_signature(
    payload_body: bytes,
    signature_header: str | None,
) -> None:
    """Verify GitHub's HMAC signature."""
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
    github_repo_id: int,
    full_name: str,
    installation_id: int,
) -> Repo:
    repo = (
        db.query(Repo)
        .filter(Repo.github_repo_id == github_repo_id)
        .first()
    )

    if repo is None:
        repo = Repo(
            github_repo_id=github_repo_id,
            full_name=full_name,
            installation_id=installation_id,
        )
        db.add(repo)
        db.flush()

        logger.info(
            f"Created repo record: {full_name}"
        )

    else:
        repo.full_name = full_name
        repo.installation_id = installation_id

    return repo


def upsert_pull_request(
    db: Session,
    repo: Repo,
    github_pr_number: int,
    title: str,
    author: str,
    status: str,
) -> PullRequest:
    pr = (
        db.query(PullRequest)
        .filter(
            PullRequest.repo_id == repo.id,
            PullRequest.github_pr_number == github_pr_number,
        )
        .first()
    )

    if pr is None:
        pr = PullRequest(
            repo_id=repo.id,
            github_pr_number=github_pr_number,
            title=title,
            author=author,
            status=status,
        )
        db.add(pr)

        logger.info(
            f"Created PR record: {repo.full_name}#{github_pr_number}"
        )

    else:
        pr.title = title
        pr.author = author
        pr.status = status

        logger.info(
            f"Updated PR record: {repo.full_name}#{github_pr_number}"
        )

    return pr


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
    db: Session = Depends(get_db),
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
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

        repository = payload.get("repository", {})
        pull_request = payload.get("pull_request", {})
        installation = payload.get("installation", {})

        github_repo_id = repository.get("id")
        repo_full_name = repository.get("full_name")
        installation_id = installation.get("id")

        pr_number = pull_request.get("number")
        title = pull_request.get("title", "")
        author = pull_request.get("user", {}).get("login", "")
        state = pull_request.get("state", "open")

        logger.info(
            f"PR event: action={action}, "
            f"repo={repo_full_name}, "
            f"pr_number={pr_number}, "
            f"installation_id={installation_id}"
        )

        if action in (
            "opened",
            "synchronize",
            "reopened",
        ):
            repo = get_or_create_repo(
                db=db,
                github_repo_id=github_repo_id,
                full_name=repo_full_name,
                installation_id=installation_id,
            )

            upsert_pull_request(
                db=db,
                repo=repo,
                github_pr_number=pr_number,
                title=title,
                author=author,
                status=state,
            )

            db.commit()

            logger.info(
                "Repository and pull request persisted successfully."
            )

            # Part 5 will trigger the actual review job here.
            logger.info(
                "This PR would trigger a review job."
            )

    return {"received": True}