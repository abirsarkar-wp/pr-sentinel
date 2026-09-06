import time
from pathlib import Path

import httpx
import jwt

from app.config import settings


def _load_private_key() -> str:
    key_path = Path(__file__).resolve().parent.parent / settings.GITHUB_PRIVATE_KEY_PATH
    return key_path.read_text()


def generate_app_jwt() -> str:
    """Create a short-lived JWT that authenticates as the GitHub App itself."""
    now = int(time.time())

    payload = {
        "iat": now - 60,
        "exp": now + (9 * 60),
        "iss": settings.GITHUB_APP_ID,
    }

    private_key = _load_private_key()

    return jwt.encode(
        payload,
        private_key,
        algorithm="RS256",
    )


async def get_installation_access_token(installation_id: str) -> str:
    """Exchange the app JWT for a short-lived token scoped to one installation."""
    app_jwt = generate_app_jwt()

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers)
        response.raise_for_status()

        return response.json()["token"]