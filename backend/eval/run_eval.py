import json
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.append(
    str(Path(__file__).resolve().parent.parent)
)

from app.database import SessionLocal
from app.embeddings import embed_documents
from app.ingestion import chunk_file, find_code_files
from app.models import CodeChunk, EvalRun, Repo
from eval.eval_agent import run_agent_review_local
from eval.scorer import score


GROUND_TRUTH_DIR = (
    Path(__file__).parent / "ground_truth"
)

DATASET_PATH = (
    Path(__file__).parent / "dataset.json"
)

MODES = [
    "full",
    "no_retrieval",
    "no_critique",
]


def clone_public_repo(
    repo_full_name: str,
    head_sha: str,
) -> Path:
    """
    Create a temporary checkout at the exact PR head SHA.
    """
    tmp_dir = Path(
        tempfile.mkdtemp(
            prefix="eval-clone-"
        )
    )

    try:
        subprocess.run(
            [
                "git",
                "init",
                str(tmp_dir),
            ],
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
        shutil.rmtree(
            tmp_dir,
            ignore_errors=True,
        )
        raise


def get_or_create_eval_repo(
    db,
    repo_full_name: str,
) -> Repo:
    repo = (
        db.query(Repo)
        .filter(
            Repo.full_name == repo_full_name
        )
        .first()
    )

    if repo is None:
        repo = Repo(
            github_repo_id=hash(
                repo_full_name
            ) % (10**9),
            full_name=repo_full_name,
            installation_id=0,
        )

        db.add(repo)
        db.commit()
        db.refresh(repo)

    return repo


def clear_eval_chunks(
    db,
    repo: Repo,
):
    """
    Remove previous evaluation chunks for this repo.
    """
    deleted = (
        db.query(CodeChunk)
        .filter(
            CodeChunk.repo_id == repo.id
        )
        .delete(
            synchronize_session=False
        )
    )

    db.commit()

    return deleted


def ingest_for_eval(
    db,
    repo: Repo,
    repo_dir: Path,
    file_paths: list[str] | None = None,
):
    """
    Ingest the selected evaluation corpus.

    We intentionally use PR-changed files only because
    the current Voyage account is restricted to 3 RPM.
    """
    clear_eval_chunks(
        db,
        repo,
    )

    if file_paths:
        files = [
            repo_dir / file_path
            for file_path in file_paths
            if (
                repo_dir / file_path
            ).is_file()
        ]
    else:
        files = find_code_files(
            repo_dir
        )

    all_chunks = []

    for file_path in files:
        all_chunks.extend(
            chunk_file(
                file_path,
                repo_dir,
            )
        )

    MAX_EVAL_CHUNKS = 20

    if len(all_chunks) > MAX_EVAL_CHUNKS:
        print(
            f"  Limiting evaluation corpus from "
            f"{len(all_chunks)} chunks to "
            f"{MAX_EVAL_CHUNKS} chunks"
        )
        all_chunks = all_chunks[:MAX_EVAL_CHUNKS]

    print(
        f"  Code files: {len(files)}"
    )

    print(
        f"  Chunks: {len(all_chunks)}"
    )

    if not all_chunks:
        return 0

    embeddings = embed_documents(
        [
            chunk["content"]
            for chunk in all_chunks
        ]
    )

    for chunk, embedding in zip(
        all_chunks,
        embeddings,
    ):
        db.add(
            CodeChunk(
                repo_id=repo.id,
                file_path=chunk[
                    "file_path"
                ],
                start_line=chunk[
                    "start_line"
                ],
                end_line=chunk[
                    "end_line"
                ],
                content=chunk[
                    "content"
                ],
                embedding=embedding,
            )
        )

    db.commit()

    return len(all_chunks)


def load_ground_truth_files() -> list[Path]:
    """
    Load only PRs explicitly listed in dataset.json.
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

    if not isinstance(
        dataset,
        list,
    ):
        raise ValueError(
            "dataset.json must contain a JSON list."
        )

    gt_files: list[Path] = []

    for entry in dataset:
        if not isinstance(
            entry,
            dict,
        ):
            raise ValueError(
                "Each dataset entry must be an object."
            )

        repo = entry.get(
            "repo"
        )

        pr_number = entry.get(
            "pr_number"
        )

        if (
            not repo
            or not isinstance(
                pr_number,
                int,
            )
        ):
            raise ValueError(
                "Each dataset entry must contain "
                "'repo' and integer 'pr_number'."
            )

        filename = (
            f"{repo.replace('/', '_')}"
            f"_{pr_number}.json"
        )

        ground_truth_file = (
            GROUND_TRUTH_DIR
            / filename
        )

        if not ground_truth_file.exists():
            print(
                f"WARNING: Missing ground truth: "
                f"{filename}"
            )
            continue

        gt_files.append(
            ground_truth_file
        )

    return gt_files


def evaluate_mode(
    db,
    repo_dir: Path,
    repo: Repo,
    data: dict,
    mode: str,
):
    """
    Run one evaluation mode and return:
    predictions, score, failure.
    """
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

        result_score = score(
            predictions,
            data["ground_truth"],
        )

        return (
            predictions,
            result_score,
            None,
        )

    except Exception as exc:
        return (
            [],
            None,
            str(exc),
        )


def main():
    db = SessionLocal()

    try:
        all_scores = {
            mode: []
            for mode in MODES
        }

        failures = {
            mode: []
            for mode in MODES
        }

        gt_files = (
            load_ground_truth_files()
        )

        if not gt_files:
            raise RuntimeError(
                "No ground-truth files found for dataset.json."
            )

        print(
            f"Evaluating against "
            f"{len(gt_files)} PRs "
            f"across modes: {MODES}\n"
        )

        for gt_file in gt_files:
            data = json.loads(
                gt_file.read_text(
                    encoding="utf-8"
                )
            )

            print(
                f"--- "
                f"{data['repo']}#"
                f"{data['pr_number']} "
                f"("
                f"{len(data['ground_truth'])}"
                f" human comments) ---"
            )

            repo_dir = clone_public_repo(
                data["repo"],
                data["head_sha"],
            )

            try:
                repo = (
                    get_or_create_eval_repo(
                        db,
                        data["repo"],
                    )
                )

                changed_files = [
                    file_data["filename"]
                    for file_data in data["files"]
                    if file_data.get(
                        "filename"
                    )
                ]

                print(
                    f"  Evaluation corpus: "
                    f"{len(changed_files)} "
                    f"changed files"
                )

                # Only full and no_critique need
                # retrieval/embedding.
                needs_embeddings = any(
                    mode in {
                        "full",
                        "no_critique",
                    }
                    for mode in MODES
                )

                if needs_embeddings:
                    ingest_for_eval(
                        db,
                        repo,
                        repo_dir,
                        changed_files,
                    )

                    print(
                        "  Ingestion OK"
                    )

                for mode in MODES:
                    # no_retrieval does not need the
                    # vector database at all.
                    if (
                        mode == "no_retrieval"
                    ):
                        clear_eval_chunks(
                            db,
                            repo,
                        )

                    predictions, result_score, failure = (
                        evaluate_mode(
                            db,
                            repo_dir,
                            repo,
                            data,
                            mode,
                        )
                    )

                    if failure:
                        failures[mode].append(
                            {
                                "repo": data[
                                    "repo"
                                ],
                                "pr_number": data[
                                    "pr_number"
                                ],
                                "error": failure,
                            }
                        )

                        print(
                            f"  [{mode}] "
                            f"FAILED: {failure}"
                        )

                        # Failed runs are NOT
                        # treated as a real
                        # zero-score prediction.
                        continue

                    all_scores[
                        mode
                    ].append(
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

        print(
            "\n=== AGGREGATE RESULTS ===\n"
        )

        report_lines = [
            "| Mode | Avg Precision | Avg Recall | Avg False-Positive Rate | Successful Runs |",
            "|---|---|---|---|---:|",
        ]

        for mode in MODES:
            scores = all_scores[
                mode
            ]

            if scores:
                avg_precision = (
                    sum(
                        item[
                            "precision"
                        ]
                        for item in scores
                    )
                    / len(scores)
                )

                avg_recall = (
                    sum(
                        item[
                            "recall"
                        ]
                        for item in scores
                    )
                    / len(scores)
                )

                avg_fp = (
                    sum(
                        item[
                            "false_positive_rate"
                        ]
                        for item in scores
                    )
                    / len(scores)
                )

                print(
                    f"{mode}: "
                    f"precision="
                    f"{avg_precision:.2f} "
                    f"recall="
                    f"{avg_recall:.2f} "
                    f"fp_rate="
                    f"{avg_fp:.2f}"
                )

                report_lines.append(
                    f"| {mode} | "
                    f"{avg_precision:.2f} | "
                    f"{avg_recall:.2f} | "
                    f"{avg_fp:.2f} | "
                    f"{len(scores)} |"
                )

                db.add(
                    EvalRun(
                        run_at=(
                            datetime.now(
                                timezone.utc
                            )
                        ),
                        dataset_name=(
                            "portfolio_eval_v1"
                        ),
                        precision=(
                            avg_precision
                        ),
                        recall=(
                            avg_recall
                        ),
                        false_positive_rate=(
                            avg_fp
                        ),
                        notes=(
                            f"mode={mode}; "
                            "changed-files corpus"
                        ),
                    )
                )

            else:
                print(
                    f"{mode}: "
                    "no successful runs"
                )

                report_lines.append(
                    f"| {mode} | "
                    "N/A | N/A | N/A | 0 |"
                )

        db.commit()

        total_failures = sum(
            len(items)
            for items in failures.values()
        )

        results_path = (
            Path(__file__).resolve().parent.parent
            / "EVAL_RESULTS.md"
        )

        report = (
            "# PR Sentinel — Evaluation Results\n\n"
            f"Evaluated against "
            f"{len(gt_files)} real merged PRs "
            "with genuine human review comments.\n\n"
            "## Evaluation scope\n\n"
            "The evaluation corpus uses PR-changed files only. "
            "This was done to keep the experiment feasible "
            "under the current Voyage AI free-tier rate limit. "
            "This is not equivalent to unrestricted "
            "full-repository retrieval.\n\n"
            + "\n".join(report_lines)
            + "\n\n"
            "## Run failures\n\n"
            f"Total failed mode runs: "
            f"{total_failures}\n\n"
        )

        for mode in MODES:
            report += (
                f"### {mode}\n\n"
            )

            if not failures[mode]:
                report += (
                    "No failed runs.\n\n"
                )
                continue

            for failure in failures[
                mode
            ]:
                report += (
                    f"- "
                    f"{failure['repo']}#"
                    f"{failure['pr_number']}: "
                    f"{failure['error']}\n"
                )

            report += "\n"

        report += (
            "## Methodology\n\n"
            "A prediction matches a human review comment "
            "when the file path matches and the predicted "
            "line is within three lines of the human-reviewed "
            "line. Agent execution failures are reported "
            "separately and are not silently converted into "
            "zero-quality predictions.\n\n"
            "Full mode = retrieval + self-critique.\n"
            "No retrieval = retrieval disabled.\n"
            "No critique = self-critique disabled.\n"
        )

        results_path.write_text(
            report,
            encoding="utf-8",
        )

        print(
            f"\nWrote {results_path}"
        )

    finally:
        db.close()


if __name__ == "__main__":
    main()
