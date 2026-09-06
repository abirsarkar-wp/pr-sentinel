import json
import httpx
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.config import settings


HEADERS = {
    "Authorization": f"Bearer {settings.GITHUB_EVAL_TOKEN}",
    "Accept": "application/vnd.github+json",
}

DATASET_PATH = Path(__file__).parent / "dataset.json"
OUTPUT_DIR = Path(__file__).parent / "ground_truth"
OUTPUT_DIR.mkdir(exist_ok=True)


def fetch_pr_data(repo: str, pr_number: int) -> dict:
    with httpx.Client(timeout=30.0) as client:
        pr_response = client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}",
            headers=HEADERS,
        )
        pr_response.raise_for_status()
        pr = pr_response.json()

        files_response = client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files",
            headers=HEADERS,
            params={"per_page": 100},
        )
        files_response.raise_for_status()
        files = files_response.json()

        comments_response = client.get(
            f"https://api.github.com/repos/{repo}/pulls/{pr_number}/comments",
            headers=HEADERS,
            params={"per_page": 100},
        )
        comments_response.raise_for_status()
        comments = comments_response.json()

    ground_truth = [
        {
            "path": comment["path"],
            "line": comment.get("line") or comment.get("original_line"),
            "body": comment["body"],
        }
        for comment in comments
        if comment.get("line") or comment.get("original_line")
    ]

    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": pr["title"],
        "body": pr.get("body"),
        "head_sha": pr["head"]["sha"],
        "files": files,
        "ground_truth": ground_truth,
    }


def main():
    dataset = json.loads(DATASET_PATH.read_text(encoding="utf-8"))

    for entry in dataset:
        repo = entry["repo"]
        pr_number = entry["pr_number"]

        print(f"Fetching {repo}#{pr_number}...")

        try:
            data = fetch_pr_data(repo, pr_number)

            output_name = f"{repo.replace('/', '_')}_{pr_number}.json"
            output_path = OUTPUT_DIR / output_name

            output_path.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )

            print(
                f"  -> {len(data['ground_truth'])} "
                f"inline human-review comments saved to {output_name}"
            )

        except Exception as exc:
            print(f"  -> FAILED: {exc}")


if __name__ == "__main__":
    main()