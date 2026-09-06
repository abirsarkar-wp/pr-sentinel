import hmac
import hashlib
import json
import logging

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings


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


@router.post("/webhooks/github")
async def github_webhook(
    request: Request,
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
        pr_number = payload.get("pull_request", {}).get("number")
        repo_full_name = payload.get("repository", {}).get("full_name")
        installation_id = payload.get("installation", {}).get("id")

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
            # Part 5 will trigger the actual review job here.
            logger.info(
                "This PR would trigger a review job."
            )

    return {"received": True}