import base64

import httpx

from app.github_auth import get_installation_access_token
from app.models import Repo


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


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