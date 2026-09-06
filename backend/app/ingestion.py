import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from sqlalchemy.orm import Session

from app.embeddings import embed_documents
from app.github_auth import get_installation_access_token
from app.models import CodeChunk, Repo


logger = logging.getLogger("pr_sentinel.ingestion")


CODE_EXTENSIONS = {
    ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java",
    ".rb", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs", ".php",
}

SKIP_DIRS = {
    ".git",
    "node_modules",
    "venv",
    ".venv",
    "__pycache__",
    "dist",
    "build",
    ".next",
    "target",
    "vendor",
}

MAX_FILE_SIZE_BYTES = 500_000
CHUNK_LINES = 60
CHUNK_OVERLAP = 15


async def clone_repo(repo: Repo) -> Path:
    """Clone the repository using a fresh GitHub App installation token."""
    token = await get_installation_access_token(
        str(repo.installation_id)
    )

    clone_url = (
        f"https://x-access-token:{token}@github.com/"
        f"{repo.full_name}.git"
    )

    tmp_dir = Path(
        tempfile.mkdtemp(prefix="pr-sentinel-")
    )

    logger.info(
        f"Cloning {repo.full_name} into {tmp_dir}"
    )

    result = subprocess.run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            clone_url,
            str(tmp_dir),
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        safe_stderr = result.stderr.replace(
            token,
            "***",
        )
        raise RuntimeError(
            f"git clone failed: {safe_stderr}"
        )

    return tmp_dir


def find_code_files(repo_dir: Path) -> list[Path]:
    """Find supported source-code files."""
    files: list[Path] = []

    for path in repo_dir.rglob("*"):
        if not path.is_file():
            continue

        if any(part in SKIP_DIRS for part in path.parts):
            continue

        if path.suffix.lower() not in CODE_EXTENSIONS:
            continue

        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            continue

        files.append(path)

    return files


def chunk_file(
    path: Path,
    repo_dir: Path,
) -> list[dict]:
    """Split a source file into overlapping line-range chunks."""
    try:
        text = path.read_text(
            encoding="utf-8",
            errors="ignore",
        )
    except Exception as exc:
        logger.warning(
            f"Skipping unreadable file {path}: {exc}"
        )
        return []

    lines = text.splitlines()

    if not lines:
        return []

    relative_path = str(
        path.relative_to(repo_dir)
    ).replace("\\", "/")

    chunks: list[dict] = []

    start = 0
    step = CHUNK_LINES - CHUNK_OVERLAP

    while start < len(lines):
        end = min(
            start + CHUNK_LINES,
            len(lines),
        )

        chunk_text = "\n".join(
            lines[start:end]
        ).strip()

        if chunk_text:
            chunks.append(
                {
                    "file_path": relative_path,
                    "start_line": start + 1,
                    "end_line": end,
                    "content": chunk_text,
                }
            )

        if end == len(lines):
            break

        start += step

    return chunks


async def ingest_repo(
    db: Session,
    repo: Repo,
) -> int:
    """Clone, chunk, embed, and store a repository."""
    repo_dir = await clone_repo(repo)

    try:
        # Remove previous chunks so re-ingestion does not duplicate data.
        db.query(CodeChunk).filter(
            CodeChunk.repo_id == repo.id
        ).delete()

        db.commit()

        code_files = find_code_files(repo_dir)

        logger.info(
            f"Found {len(code_files)} code files to chunk "
            f"in {repo.full_name}"
        )

        all_chunks: list[dict] = []

        for file_path in code_files:
            all_chunks.extend(
                chunk_file(
                    file_path,
                    repo_dir,
                )
            )

        if not all_chunks:
            logger.warning(
                "No chunks produced — repository may be "
                "empty or all files were filtered out."
            )
            return 0

        logger.info(
            f"Embedding {len(all_chunks)} chunks..."
        )

        texts = [
            chunk["content"]
            for chunk in all_chunks
        ]

        embeddings = embed_documents(texts)

        for chunk, embedding in zip(
            all_chunks,
            embeddings,
        ):
            db.add(
                CodeChunk(
                    repo_id=repo.id,
                    file_path=chunk["file_path"],
                    start_line=chunk["start_line"],
                    end_line=chunk["end_line"],
                    content=chunk["content"],
                    embedding=embedding,
                )
            )

        db.commit()

        logger.info(
            f"Stored {len(all_chunks)} code chunks "
            f"for {repo.full_name}"
        )

        return len(all_chunks)

    finally:
        shutil.rmtree(
            repo_dir,
            ignore_errors=True,
        )