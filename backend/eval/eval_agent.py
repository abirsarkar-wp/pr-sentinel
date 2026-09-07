import json
from pathlib import Path

import sys

sys.path.append(
    str(Path(__file__).resolve().parent.parent)
)

from app.agent import (
    client,
    MODEL,
    SYSTEM_PROMPT,
    GATHER_TOOLS,
    SUBMIT_FINDINGS_TOOL,
    build_diff_summary,
    MAX_GATHER_TURNS,
)
from app.schemas import FindingsSubmission
from app.retrieval import search_code


def execute_tool_local(
    repo_dir: Path,
    db,
    repo_id: int,
    tool_name: str,
    tool_input: dict,
) -> str:
    if tool_name == "read_file":
        try:
            return (
                repo_dir / tool_input["file_path"]
            ).read_text(
                encoding="utf-8",
                errors="ignore",
            )[:8000]
        except Exception as exc:
            return f"Error reading file: {exc}"

    if tool_name in (
        "search_codebase",
        "get_related_tests",
    ):
        query = (
            tool_input.get("query")
            or f"test file for "
            f"{tool_input.get('file_path', '')}"
        )

        return json.dumps(
            search_code(
                db,
                repo_id,
                query,
                top_k=5,
            )
        )

    return f"Unknown tool: {tool_name}"


def parse_submission(
    tool_input: dict,
) -> FindingsSubmission:
    return FindingsSubmission.model_validate(
        tool_input
    )


def direct_submission(
    messages: list[dict],
    retries: int = 2,
) -> FindingsSubmission:
    """
    Direct structured-output path used when retrieval
    is disabled and for the critique step.
    """

    for attempt in range(retries + 1):
        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=[SUBMIT_FINDINGS_TOOL],
            tool_choice={
                "type": "tool",
                "name": "submit_findings",
            },
            messages=messages,
        )

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        tool_use = next(
            (
                block
                for block in response.content
                if block.type == "tool_use"
                and block.name == "submit_findings"
            ),
            None,
        )

        if tool_use is None:
            if attempt < retries:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Call submit_findings now "
                            "with the complete required schema."
                        ),
                    }
                )
                continue

            raise RuntimeError(
                "Claude did not return submit_findings."
            )

        try:
            result = parse_submission(
                tool_use.input
            )

            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": "Valid submission received.",
                        }
                    ],
                }
            )

            return result

        except Exception as exc:
            if attempt >= retries:
                raise RuntimeError(
                    "Invalid submit_findings output: "
                    f"{exc}"
                ) from exc

            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": tool_use.id,
                            "content": (
                                f"Validation error: {exc}"
                            ),
                        }
                    ],
                }
            )

            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Call submit_findings again. "
                        "The 'findings' field is required. "
                        "Use an empty array if there are no findings."
                    ),
                }
            )

    raise RuntimeError(
        "Unable to obtain valid structured output."
    )


def run_no_retrieval(
    pr_data: dict,
    files: list[dict],
) -> FindingsSubmission:
    """
    No-retrieval ablation.

    IMPORTANT:
    This path deliberately does not expose any retrieval
    tools and does not enter the tool execution loop.
    """

    diff_summary = build_diff_summary(
        files
    )

    messages = [
        {
            "role": "user",
            "content": (
                "Review this pull request without "
                "using any external codebase retrieval.\n\n"
                f"Title: {pr_data['title']}\n"
                f"Description: "
                f"{pr_data.get('body') or '(none)'}\n\n"
                "Changed files:\n\n"
                f"{diff_summary}"
            ),
        }
    ]

    return direct_submission(
        messages
    )


def run_agent_review_local(
    db,
    repo_dir: Path,
    repo_id: int,
    pr_data: dict,
    files: list[dict],
    use_retrieval: bool = True,
    use_critique: bool = True,
):
    # ---------------------------------------------
    # NO RETRIEVAL ABLATION
    # ---------------------------------------------
    if not use_retrieval:
        return run_no_retrieval(
            pr_data,
            files,
        )

    # ---------------------------------------------
    # NORMAL / FULL GATHER PHASE
    # ---------------------------------------------

    diff_summary = build_diff_summary(
        files
    )

    messages = [
        {
            "role": "user",
            "content": (
                "Review this pull request.\n\n"
                f"Title: {pr_data['title']}\n"
                f"Description: "
                f"{pr_data.get('body') or '(none)'}\n\n"
                "Changed files:\n\n"
                f"{diff_summary}"
            ),
        }
    ]

    turn = 0
    draft = None

    while turn < MAX_GATHER_TURNS:
        turn += 1

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=GATHER_TOOLS,
            messages=messages,
        )

        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        if response.stop_reason != "tool_use":
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Please continue reviewing and "
                        "call submit_findings when ready."
                    ),
                }
            )
            continue

        tool_results = []
        submitted_input = None

        for block in response.content:
            if block.type != "tool_use":
                continue

            if block.name == "submit_findings":
                submitted_input = block.input

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": "Draft received.",
                    }
                )

            else:
                result = execute_tool_local(
                    repo_dir,
                    db,
                    repo_id,
                    block.name,
                    block.input,
                )

                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        # IMPORTANT:
        # This user message immediately follows the
        # assistant tool_use message.
        messages.append(
            {
                "role": "user",
                "content": tool_results,
            }
        )

        if submitted_input is not None:
            try:
                draft = parse_submission(
                    submitted_input
                )
                break

            except Exception as exc:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "The submit_findings payload "
                            "was invalid.\n\n"
                            f"Validation error: {exc}\n\n"
                            "Call submit_findings again with "
                            "the complete required schema."
                        ),
                    }
                )

    if draft is None:
        raise RuntimeError(
            "No valid draft produced within max turns"
        )

    if not use_critique:
        return draft

    # ---------------------------------------------
    # CRITIQUE PHASE
    # ---------------------------------------------

    critique_messages = messages + [
        {
            "role": "user",
            "content": (
                "Critique your draft findings for "
                "false positives, duplicates, and nitpicks. "
                "Then call submit_findings with the final list."
            ),
        }
    ]

    return direct_submission(
        critique_messages,
        retries=2,
    )