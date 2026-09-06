import os
import requests
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_EVAL_TOKEN")

if not TOKEN:
    raise RuntimeError("GITHUB_EVAL_TOKEN is not loaded")

HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/vnd.github+json",
}

REPOS = [
    "fastapi/fastapi",
    "pydantic/pydantic",
    "pytest-dev/pytest",
    "psf/requests",
    "encode/httpx",
]

def is_human(login: str) -> bool:
    return not login.endswith("[bot]")

def get_candidates(repo: str):
    print(f"\n=== {repo} ===")

    params = {
        "q": f"repo:{repo} is:pr is:merged review:changes_requested",
        "per_page": 10,
        "sort": "updated",
        "order": "desc",
    }

    r = requests.get(
        "https://api.github.com/search/issues",
        headers=HEADERS,
        params=params,
        timeout=30,
    )
    r.raise_for_status()

    items = r.json().get("items", [])

    for item in items:
        number = item["number"]

        reviews_url = f"https://api.github.com/repos/{repo}/pulls/{number}/reviews"
        comments_url = f"https://api.github.com/repos/{repo}/pulls/{number}/comments"

        reviews = requests.get(
            reviews_url,
            headers=HEADERS,
            params={"per_page": 100},
            timeout=30,
        ).json()

        comments = requests.get(
            comments_url,
            headers=HEADERS,
            params={"per_page": 100},
            timeout=30,
        ).json()

        human_reviews = [
            x for x in reviews
            if x.get("user")
            and is_human(x["user"]["login"])
            and x.get("state") in {"CHANGES_REQUESTED", "COMMENTED", "APPROVED"}
        ]

        human_inline_comments = [
            x for x in comments
            if x.get("user")
            and is_human(x["user"]["login"])
            and x.get("path")
            and (x.get("line") or x.get("original_line"))
        ]

        if human_reviews and human_inline_comments:
            print(
                f"#{number} | {item['title']}\n"
                f"  human reviews: {len(human_reviews)} | "
                f"human inline comments: {len(human_inline_comments)}\n"
                f"  https://github.com/{repo}/pull/{number}\n"
            )

for repo in REPOS:
    try:
        get_candidates(repo)
    except Exception as e:
        print(f"ERROR for {repo}: {e}")