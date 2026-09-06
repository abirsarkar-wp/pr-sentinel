import base64
import re
import httpx
from app.schemas import Finding as FindingSchema
from app.github_auth import get_installation_access_token
from app.models import Repo
MIN_CONFIDENCE_TO_POST = 0.5

def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

def get_commentable_lines(patch: str) -> set[int]:
    """
    Return line numbers in the NEW version of a file that are
    valid targets for a GitHub inline review comment.
    """
    if not patch:
        return set()

    commentable = set()
    new_line_num = 0

    for line in patch.splitlines():
        if line.startswith("@@"):
            match = re.match(
                r"@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@",
                line,
            )

            if match:
                new_line_num = int(match.group(1))

            continue

        if line.startswith("\\"):
            # "\ No newline at end of file"
            continue

        if line.startswith("+"):
            commentable.add(new_line_num)
            new_line_num += 1

        elif line.startswith("-"):
            # Removed lines do not exist in the new version.
            continue

        else:
            # Unchanged context line.
            commentable.add(new_line_num)
            new_line_num += 1

    return commentable

def _format_comment_body(
    finding: FindingSchema,
) -> str:
    severity_emoji = {
        "low": "🔵",
        "medium": "🟡",
        "high": "🟠",
        "critical": "🔴",
    }

    emoji = severity_emoji.get(
        finding.severity,
        "⚪",
    )

    lines = [
        f"{emoji} **{finding.category.upper()}** "
        f"({finding.severity}, "
        f"confidence {finding.confidence:.0%})",
        "",
        finding.explanation,
    ]

    if finding.suggested_fix:
        lines += [
            "",
            f"**Suggested fix:** {finding.suggested_fix}",
        ]

    return "\n".join(lines)


def _build_review_body(
    summary: str,
    overflow_findings: list[FindingSchema],
) -> str:
    parts = [
        "### 🤖 PR Sentinel automated review",
        "",
        summary,
    ]

    if overflow_findings:
        parts += [
            "",
            "**Additional findings outside the diff view:**",
            "",
        ]

        for finding in overflow_findings:
            parts.append(
                f"- `{finding.file}:{finding.line_start}` "
                f"— {finding.explanation}"
            )

    parts += [
        "",
        "_This review was generated automatically. "
        "Findings are suggestions, not blockers — use your judgment._",
    ]

    return "\n".join(parts)


async def post_review(
    repo: Repo,
    pr_number: int,
    summary: str,
    findings: list[FindingSchema],
    files: list[dict],
) -> dict:
    token = await get_installation_access_token(
        str(repo.installation_id)
    )

    commentable_by_file = {
        file["filename"]: get_commentable_lines(
            file.get("patch", "")
        )
        for file in files
    }

    postable = [
        finding
        for finding in findings
        if finding.confidence >= MIN_CONFIDENCE_TO_POST
    ]

    skipped_low_confidence = (
        len(findings) - len(postable)
    )

    inline_comments = []
    overflow_findings = []

    for finding in postable:
        commentable_lines = commentable_by_file.get(
            finding.file,
            set(),
        )

        if finding.line_start in commentable_lines:
            inline_comments.append(
                {
                    "path": finding.file,
                    "line": finding.line_start,
                    "side": "RIGHT",
                    "body": _format_comment_body(
                        finding
                    ),
                }
            )
        else:
            overflow_findings.append(finding)

    body = _build_review_body(
        summary,
        overflow_findings,
    )

    if skipped_low_confidence:
        body += (
            f"\n\n_{skipped_low_confidence} "
            "low-confidence finding(s) were withheld._"
        )

    payload = {
        "body": body,
        "event": "COMMENT",
        "comments": inline_comments,
    }

    url = (
        f"https://api.github.com/repos/"
        f"{repo.full_name}/pulls/{pr_number}/reviews"
    )

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            headers=_headers(token),
            json=payload,
        )

        response.raise_for_status()

        return response.json()
async def get_pr(repo: Repo, pr_number: int) -> dict:
    """Get basic pull request information."""
    token = await get_installation_access_token(
        str(repo.installation_id)
    )

    url = (
        f"https://api.github.com/repos/"
        f"{repo.full_name}/pulls/{pr_number}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=_headers(token),
        )
        response.raise_for_status()
        data = response.json()

    return {
        "number": data["number"],
        "title": data["title"],
        "body": data.get("body"),
        "head_sha": data["head"]["sha"],
    }


async def get_pr_files(
    repo: Repo,
    pr_number: int,
) -> list[dict]:
    """Get files changed by a pull request."""
    token = await get_installation_access_token(
        str(repo.installation_id)
    )

    url = (
        f"https://api.github.com/repos/"
        f"{repo.full_name}/pulls/{pr_number}/files"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=_headers(token),
            params={"per_page": 100},
        )
        response.raise_for_status()

        return response.json()


async def get_file_content(
    repo: Repo,
    path: str,
    ref: str,
) -> str:
    """Get the contents of a repository file at a specific commit."""
    token = await get_installation_access_token(
        str(repo.installation_id)
    )

    url = (
        f"https://api.github.com/repos/"
        f"{repo.full_name}/contents/{path}"
    )

    async with httpx.AsyncClient() as client:
        response = await client.get(
            url,
            headers=_headers(token),
            params={"ref": ref},
        )
        response.raise_for_status()
        data = response.json()

    return base64.b64decode(
        data["content"]
    ).decode(
        "utf-8",
        errors="ignore",
    )