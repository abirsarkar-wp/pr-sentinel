import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models import CodeChunk, EvalRun, Repo
from app.embeddings import embed_documents
from app.ingestion import chunk_file, find_code_files
from eval.eval_agent import run_agent_review_local
from eval.scorer import score


GROUND_TRUTH_DIR = Path(__file__).parent / "ground_truth"
DATASET_PATH = Path(__file__).parent / "dataset.json"

MODES = ["full", "no_retrieval", "no_critique"]


def clone_public_repo(repo_full_name: str, head_sha: str) -> Path:
    """
    Create a temporary repository checkout containing exactly the PR head SHA.
    Only the required commit is fetched.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="eval-clone-"))

    try:
        subprocess.run(
            ["git", "init", str(tmp_dir)],
            check=True,
            stdout=subprocess.DEVNULL,
        )

        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_dir),
                "remote",
                "add",
                "origin",
                f"https://github.com/{repo_full_name}.git",
            ],
            check=True,
        )

        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_dir),
                "fetch",
                "--depth",
                "1",
                "origin",
                head_sha,
            ],
            check=True,
        )

        subprocess.run(
            [
                "git",
                "-C",
                str(tmp_dir),
                "checkout",
                "--detach",
                "FETCH_HEAD",
            ],
            check=True,
        )

        return tmp_dir

    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def get_or_create_eval_repo(db, repo_full_name: str) -> Repo:
    repo = (
        db.query(Repo)
        .filter(Repo.full_name == repo_full_name)
        .first()
    )

    if repo is None:
        repo = Repo(
            github_repo_id=hash(repo_full_name) % (10**9),
            full_name=repo_full_name,
            installation_id=0,
        )

        db.add(repo)
        db.commit()
        db.refresh(repo)

    return repo


def ingest_for_eval(
    db,
    repo: Repo,
    repo_dir: Path,
    file_paths: list[str] | None = None,
):
    """
    Ingest either the whole repository or only selected files.

    For the real evaluation we use the full repository so retrieval
    can actually find related code outside the PR diff.
    """
    db.query(CodeChunk).filter(
        CodeChunk.repo_id == repo.id
    ).delete()

    db.commit()

    if file_paths:
        files = [
            repo_dir / file_path
            for file_path in file_paths
            if (repo_dir / file_path).is_file()
        ]
    else:
        files = find_code_files(repo_dir)

    all_chunks = []

    for file_path in files:
        all_chunks.extend(
            chunk_file(file_path, repo_dir)
        )

    if not all_chunks:
        return

    embeddings = embed_documents(
        [chunk["content"] for chunk in all_chunks]
    )

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


def load_ground_truth_files() -> list[Path]:
    """
    Load only the PRs explicitly listed in dataset.json.

    This prevents stale JSON files in ground_truth/ from
    accidentally being included in the evaluation.
    """
    if not DATASET_PATH.exists():
        raise FileNotFoundError(
            f"Dataset not found: {DATASET_PATH}"
        )

    dataset = json.loads(
        DATASET_PATH.read_text(
            encoding="utf-8"
        )
    )

    if not isinstance(dataset, list):
        raise ValueError(
            "dataset.json must contain a JSON list."
        )

    gt_files: list[Path] = []

    for entry in dataset:
        if not isinstance(entry, dict):
            raise ValueError(
                "Each dataset entry must be an object."
            )

        repo = entry.get("repo")
        pr_number = entry.get("pr_number")

        if not repo or not isinstance(pr_number, int):
            raise ValueError(
                "Each dataset entry must contain "
                "'repo' and integer 'pr_number'."
            )

        filename = (
            f"{repo.replace('/', '_')}_{pr_number}.json"
        )

        ground_truth_file = (
            GROUND_TRUTH_DIR / filename
        )

        if not ground_truth_file.exists():
            print(
                f"WARNING: Missing ground truth: "
                f"{filename}"
            )
            continue

        gt_files.append(ground_truth_file)

    return gt_files


def main():
    db = SessionLocal()

    try:
        all_scores = {
            mode: []
            for mode in MODES
        }

        gt_files = load_ground_truth_files()

        if not gt_files:
            raise RuntimeError(
                "No ground-truth files found for dataset.json."
            )

        print(
            f"Evaluating against {len(gt_files)} PRs "
            f"across modes: {MODES}\n"
        )

        for gt_file in gt_files:
            data = json.loads(
                gt_file.read_text(
                    encoding="utf-8"
                )
            )

            print(
                f"--- {data['repo']}#{data['pr_number']} "
                f"({len(data['ground_truth'])} "
                f"human comments) ---"
            )

            repo_dir = clone_public_repo(
                data["repo"],
                data["head_sha"],
            )

            try:
                repo = get_or_create_eval_repo(
                    db,
                    data["repo"],
                )

                # Evaluation corpus:
                # use only files changed by the PR.
                #
                # This keeps the evaluation feasible under the
                # current Voyage free-tier rate limit.
                changed_files = [
                    file_data["filename"]
                    for file_data in data["files"]
                    if file_data.get("filename")
                ]

                print(
                    f"  Evaluation corpus: {len(changed_files)} changed files"
                )

                ingest_for_eval(
                    db,
                    repo,
                    repo_dir,
                    changed_files,
                )

                for mode in MODES:
                    use_retrieval = (
                        mode != "no_retrieval"
                    )

                    use_critique = (
                        mode != "no_critique"
                    )

                    try:
                        result = run_agent_review_local(
                            db,
                            repo_dir,
                            repo.id,
                            data,
                            data["files"],
                            use_retrieval=use_retrieval,
                            use_critique=use_critique,
                        )

                        predictions = [
                            finding.model_dump()
                            for finding in result.findings
                        ]

                    except Exception as exc:
                        print(
                            f"  [{mode}] FAILED: {exc}"
                        )

                        predictions = []

                    result_score = score(
                        predictions,
                        data["ground_truth"],
                    )

                    all_scores[mode].append(
                        result_score
                    )

                    print(
                        f"  [{mode}] "
                        f"precision="
                        f"{result_score['precision']:.2f} "
                        f"recall="
                        f"{result_score['recall']:.2f} "
                        f"fp_rate="
                        f"{result_score['false_positive_rate']:.2f}"
                    )

            finally:
                shutil.rmtree(
                    repo_dir,
                    ignore_errors=True,
                )

        print("\n=== AGGREGATE RESULTS ===\n")

        report_lines = [
            "| Mode | Avg Precision | Avg Recall | Avg False-Positive Rate |",
            "|---|---|---|---|",
        ]

        for mode in MODES:
            scores = all_scores[mode]

            if not scores:
                continue

            avg_precision = (
                sum(
                    item["precision"]
                    for item in scores
                )
                / len(scores)
            )

            avg_recall = (
                sum(
                    item["recall"]
                    for item in scores
                )
                / len(scores)
            )

            avg_fp = (
                sum(
                    item["false_positive_rate"]
                    for item in scores
                )
                / len(scores)
            )

            print(
                f"{mode}: "
                f"precision={avg_precision:.2f} "
                f"recall={avg_recall:.2f} "
                f"fp_rate={avg_fp:.2f}"
            )

            report_lines.append(
                f"| {mode} | "
                f"{avg_precision:.2f} | "
                f"{avg_recall:.2f} | "
                f"{avg_fp:.2f} |"
            )

            db.add(
                EvalRun(
                    run_at=datetime.now(timezone.utc),
                    dataset_name="portfolio_eval_v1",
                    precision=avg_precision,
                    recall=avg_recall,
                    false_positive_rate=avg_fp,
                    notes=f"mode={mode}",
                )
            )

        db.commit()

        results_path = (
            Path(__file__).resolve().parent.parent
            / "EVAL_RESULTS.md"
        )

        results_path.write_text(
            "# PR Sentinel — Evaluation Results\n\n"
            f"Evaluated against {len(gt_files)} "
            "real merged PRs with genuine human "
            "review comments.\n\n"
            + "\n".join(report_lines)
            + (
                "\n\n_Full mode = retrieval + "
                "self-critique. Ablations remove "
                "one component at a time._\n"
            ),
            encoding="utf-8",
        )

        print(
            f"\nWrote {results_path}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
