import json
import logging
import time

from google import genai
from sqlalchemy.orm import Session

from app.config import settings
from app.github_api import get_file_content
from app.models import Repo
from app.retrieval import search_code
from app.schemas import FindingsSubmission


logger = logging.getLogger("pr_sentinel.agent")


client = genai.Client(api_key=settings.GEMINI_API_KEY)

MODEL = "gemini-3.5-flash-lite"
MAX_GATHER_TURNS = 4


SYSTEM_PROMPT = """You are a senior software engineer performing a pull request code review.

Only flag things a senior engineer would actually comment on in a real review. Do not nitpick
formatting or style issues that a linter would already catch. Focus on bugs, security issues,
performance problems, missing test coverage, and genuinely unclear or risky code.

You have tools to read files and search the codebase for context beyond the diff — use them
when the diff alone isn't enough to judge whether something is actually a problem (e.g. to check
how a changed function is called elsewhere, or whether tests exist for it).

Every finding must cite a specific file and line range from the diff. Assign a severity
(low/medium/high/critical) and a confidence score (0-1) reflecting how sure you are this is a
real issue, not a guess.

When you have gathered enough context, call submit_findings with your complete list of findings
and a short summary of the PR.
"""


def _function_tool(
    name: str,
    description: str,
    parameters: dict,
) -> dict:
    return {
        "type": "function",
        "name": name,
        "description": description,
        "parameters": parameters,
    }


READ_FILE_TOOL = _function_tool(
    "read_file",
    (
        "Read the full contents of a file in the repository "
        "at the PR's head commit."
    ),
    {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path relative to repo root",
            },
        },
        "required": ["file_path"],
    },
)


SEARCH_CODEBASE_TOOL = _function_tool(
    "search_codebase",
    (
        "Semantic search over the repository's code. "
        "Use natural language or code-like queries."
    ),
    {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language or code-like search query",
            },
        },
        "required": ["query"],
    },
)


GET_RELATED_TESTS_TOOL = _function_tool(
    "get_related_tests",
    (
        "Find test files related to a given source file, "
        "to check test coverage."
    ),
    {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Source file path relative to repo root",
            },
        },
        "required": ["file_path"],
    },
)


SUBMIT_FINDINGS_TOOL = _function_tool(
    "submit_findings",
    "Submit the final list of code review findings for this PR.",
    FindingsSubmission.model_json_schema(),
)


GATHER_TOOLS = [
    READ_FILE_TOOL,
    SEARCH_CODEBASE_TOOL,
    GET_RELATED_TESTS_TOOL,
]


SUBMIT_TOOL = [SUBMIT_FINDINGS_TOOL]


def build_diff_summary(files: list[dict]) -> str:
    parts = []

    for file in files:
        patch = file.get(
            "patch",
            "(no textual diff available - binary or too large)",
        )

        parts.append(
            f"### {file['filename']} "
            f"({file['status']}, "
            f"+{file['additions']}/-{file['deletions']})\n"
            f"```diff\n{patch}\n```"
        )

    return "\n\n".join(parts)


async def execute_tool(
    repo: Repo,
    db: Session,
    head_sha: str,
    tool_name: str,
    tool_input: dict,
) -> str:

    if tool_name == "read_file":
        try:
            content = await get_file_content(
                repo,
                tool_input["file_path"],
                ref=head_sha,
            )
        except Exception as exc:
            return f"Error reading file: {exc}"

        return content[:8000]

    if tool_name == "search_codebase":
        results = search_code(
            db,
            repo.id,
            tool_input["query"],
            top_k=5,
        )
        return json.dumps(results)

    if tool_name == "get_related_tests":
        results = search_code(
            db,
            repo.id,
            f"test file for {tool_input['file_path']}",
            top_k=5,
        )
        return json.dumps(results)

    return f"Unknown tool: {tool_name}"


def _step_for_trace(step) -> dict:
    try:
        return step.model_dump(mode="json")
    except AttributeError:
        return {
            "type": getattr(step, "type", None),
            "name": getattr(step, "name", None),
            "arguments": getattr(step, "arguments", None),
            "id": getattr(step, "id", None),
        }


def _add_usage(total_tokens: int, interaction) -> int:
    usage = getattr(interaction, "usage", None)

    if usage is None:
        return total_tokens

    return total_tokens + int(
        getattr(usage, "total_input_tokens", 0)
        + getattr(usage, "total_output_tokens", 0)
    )


async def _run_gather_turn(
    interaction,
    repo: Repo,
    db: Session,
    pr_data: dict,
    traces: list,
    total_tokens: int,
    turn: int,
):
    function_results = []
    submitted_input = None

    total_tokens = _add_usage(
        total_tokens,
        interaction,
    )

    traces.append(
        {
            "turn": turn,
            "role": "gather",
            "content": [
                _step_for_trace(step)
                for step in interaction.steps
            ],
            "latency_ms": 0,
        }
    )

    for step in interaction.steps:
        if step.type != "function_call":
            continue

        if step.name == "submit_findings":
            submitted_input = step.arguments

            function_results.append(
                {
                    "type": "function_result",
                    "name": step.name,
                    "call_id": step.id,
                    "result": [
                        {
                            "type": "text",
                            "text": "Draft received.",
                        }
                    ],
                }
            )

        else:
            result = await execute_tool(
                repo,
                db,
                pr_data["head_sha"],
                step.name,
                step.arguments,
            )

            function_results.append(
                {
                    "type": "function_result",
                    "name": step.name,
                    "call_id": step.id,
                    "result": [
                        {
                            "type": "text",
                            "text": result,
                        }
                    ],
                }
            )

    return (
        function_results,
        submitted_input,
        total_tokens,
    )


async def run_agent_review(
    db: Session,
    repo: Repo,
    pr_data: dict,
    files: list[dict],
):
    """
    Run the full Gemini plan -> gather -> draft -> critique loop.

    Returns:
        final,
        draft,
        traces,
        total_tokens,
        turns
    """

    diff_summary = build_diff_summary(files)

    initial_input = (
        "Review this pull request.\n\n"
        f"Title: {pr_data['title']}\n"
        f"Description: {pr_data.get('body') or '(none)'}\n\n"
        "Changed files:\n\n"
        f"{diff_summary}"
    )

    traces = []
    total_tokens = 0
    turn = 0
    draft: FindingsSubmission | None = None

    # Phase A: gather context + produce a draft.
    interaction = client.interactions.create(
        model=MODEL,
        input=initial_input,
        system_instruction=SYSTEM_PROMPT,
        tools=GATHER_TOOLS + SUBMIT_TOOL,
    )

    while turn < MAX_GATHER_TURNS:
        turn += 1

        start = time.time()

        (
            function_results,
            submitted_input,
            total_tokens,
        ) = await _run_gather_turn(
            interaction,
            repo,
            db,
            pr_data,
            traces,
            total_tokens,
            turn,
        )

        latency_ms = int(
            (time.time() - start) * 1000
        )

        traces[-1]["latency_ms"] = latency_ms

        if submitted_input is not None:
            try:
                draft = FindingsSubmission.model_validate(
                    submitted_input
                )

                break

            except Exception as exc:
                logger.warning(
                    "Gemini submit_findings validation failed: %s",
                    exc,
                )

                if not function_results:
                    raise RuntimeError(
                        f"Draft submission failed validation: {exc}"
                    ) from exc

                retry_input = list(function_results)

                retry_input.append(
                    {
                        "type": "text",
                        "text": (
                            "Your submit_findings call did not match "
                            f"the required schema: {exc}. "
                            "Please fix it and call submit_findings "
                            "again."
                        ),
                    }
                )

                interaction = client.interactions.create(
                    model=MODEL,
                    previous_interaction_id=interaction.id,
                    input=retry_input,
                    tools=GATHER_TOOLS + SUBMIT_TOOL,
                )

                continue

        if function_results:
            interaction = client.interactions.create(
                model=MODEL,
                previous_interaction_id=interaction.id,
                input=function_results,
                tools=GATHER_TOOLS + SUBMIT_TOOL,
            )
        else:
            interaction = client.interactions.create(
                model=MODEL,
                previous_interaction_id=interaction.id,
                input=(
                    "Continue reviewing the PR. Use the available "
                    "tools when you need more context, and when "
                    "you are ready, call submit_findings with "
                    "your complete draft findings."
                ),
                tools=GATHER_TOOLS + SUBMIT_TOOL,
            )

    if draft is None:
        raise RuntimeError(
            "Agent did not produce a valid draft within "
            f"{MAX_GATHER_TURNS} turns"
        )

    # Phase B: self-critique.
    critique_input = (
        "Review this pull request again using the draft findings below.\n\n"
        f"PR title: {pr_data['title']}\n\n"
        "Draft findings:\n"
        f"{draft.model_dump_json(indent=2)}\n\n"
        "Now critique the draft findings. Remove anything that is "
        "a false positive, a duplicate, or too minor to raise in a "
        "real review. Keep only actionable findings grounded in "
        "the PR diff. Call submit_findings with the final cleaned-up "
        "list."
    )

    start = time.time()

    critique_response = client.interactions.create(
    model=MODEL,
    input=critique_input,
    system_instruction=SYSTEM_PROMPT,
    tools=SUBMIT_TOOL,
    generation_config={
        "tool_choice": {
            "allowed_tools": {
                "mode": "any",
                "tools": ["submit_findings"],
            }
        }
    },
)

    latency_ms = int(
        (time.time() - start) * 1000
    )

    total_tokens = _add_usage(
        total_tokens,
        critique_response,
    )

    turn += 1

    final_block = next(
        (
            step
            for step in critique_response.steps
            if step.type == "function_call"
            and step.name == "submit_findings"
        ),
        None,
    )

    if final_block is None:
        raise RuntimeError(
            "Gemini critique did not call submit_findings"
        )

    final = FindingsSubmission.model_validate(
        final_block.arguments
    )

    traces.append(
        {
            "turn": turn,
            "role": "critique",
            "content": [
                _step_for_trace(step)
                for step in critique_response.steps
            ],
            "latency_ms": latency_ms,
        }
    )

    return (
        final,
        draft,
        traces,
        total_tokens,
        turn,
    )
