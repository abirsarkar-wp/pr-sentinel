import json
import logging
import time

from anthropic import Anthropic
from sqlalchemy.orm import Session

from app.config import settings
from app.github_api import get_file_content
from app.models import Repo
from app.retrieval import search_code
from app.schemas import FindingsSubmission


logger = logging.getLogger("pr_sentinel.agent")


client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

MODEL = "claude-sonnet-5"
MAX_GATHER_TURNS = 6


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


READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read the full contents of a file in the repository "
        "at the PR's head commit."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Path relative to repo root",
            }
        },
        "required": ["file_path"],
    },
}


SEARCH_CODEBASE_TOOL = {
    "name": "search_codebase",
    "description": (
        "Semantic search over the repository's code. "
        "Use natural language or code-like queries."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
            }
        },
        "required": ["query"],
    },
}


GET_RELATED_TESTS_TOOL = {
    "name": "get_related_tests",
    "description": (
        "Find test files related to a given source file, "
        "to check test coverage."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
            }
        },
        "required": ["file_path"],
    },
}


SUBMIT_FINDINGS_TOOL = {
    "name": "submit_findings",
    "description": (
        "Submit the final list of code review findings for this PR."
    ),
    "input_schema": FindingsSubmission.model_json_schema(),
}


GATHER_TOOLS = [
    READ_FILE_TOOL,
    SEARCH_CODEBASE_TOOL,
    GET_RELATED_TESTS_TOOL,
    SUBMIT_FINDINGS_TOOL,
]


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

        # Prevent one huge file from consuming the whole context.
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


async def run_agent_review(
    db: Session,
    repo: Repo,
    pr_data: dict,
    files: list[dict],
):
    """
    Run the full plan -> gather -> draft -> critique loop.

    Returns:
        final,
        draft,
        traces,
        total_tokens,
        turns
    """

    diff_summary = build_diff_summary(files)

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

    traces = []
    total_tokens = 0
    turn = 0
    draft: FindingsSubmission | None = None

    # Phase A: gather context + produce a draft.
    while turn < MAX_GATHER_TURNS:
        turn += 1
        start = time.time()

        response = client.messages.create(
            model=MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=GATHER_TOOLS,
            messages=messages,
        )

        latency_ms = int(
            (time.time() - start) * 1000
        )

        total_tokens += (
            response.usage.input_tokens
            + response.usage.output_tokens
        )

        traces.append(
            {
                "turn": turn,
                "role": "gather",
                "content": [
                    block.model_dump(mode="json")
                    for block in response.content
                ],
                "latency_ms": latency_ms,
            }
        )

        # Always append Claude's response first.
        messages.append(
            {
                "role": "assistant",
                "content": response.content,
            }
        )

        # Collect every tool call from this Claude response.
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
                result = await execute_tool(
                    repo,
                    db,
                    pr_data["head_sha"],
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

        # If Claude used tools, the tool_result message MUST
        # immediately follow the assistant tool_use message.
        if tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": tool_results,
                }
            )

        if submitted_input is not None:
            try:
                draft = FindingsSubmission.model_validate(
                    submitted_input
                )

            except Exception as exc:
                # We already supplied the required tool_result.
                # Now a separate user message can explain the
                # validation problem.
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "Your submit_findings call did not match "
                            f"the required schema: {exc}. "
                            "Please fix it and call submit_findings "
                            "again."
                        ),
                    }
                )
                continue

            break

        # If Claude returned ordinary text without using a tool,
        # explicitly ask it to continue with submit_findings.
        if not tool_results:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "Continue reviewing the PR. Use the available "
                        "tools when you need more context, and when "
                        "you are ready, call submit_findings with "
                        "your complete draft findings."
                    ),
                }
            )

    if draft is None:
        raise RuntimeError(
            "Agent did not produce a valid draft within "
            f"{MAX_GATHER_TURNS} turns"
        )

    # Phase B: self-critique.
    critique_messages = [
    {
        "role": "user",
        "content": (
            "Review this pull request again using the draft findings "
            "below.\n\n"
            f"PR title: {pr_data['title']}\n\n"
            "Draft findings:\n"
            f"{draft.model_dump_json(indent=2)}\n\n"
            "Now critique the draft findings. Remove anything that is "
            "a false positive, a duplicate, or too minor to raise in a "
            "real review. Keep only actionable findings grounded in "
            "the PR diff. Call submit_findings with the final cleaned-up "
            "list."
        ),
    }
    ]

    start = time.time()

    critique_response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        tools=[SUBMIT_FINDINGS_TOOL],
        tool_choice={
            "type": "tool",
            "name": "submit_findings",
        },
        messages=critique_messages,
    )

    latency_ms = int(
        (time.time() - start) * 1000
    )

    total_tokens += (
        critique_response.usage.input_tokens
        + critique_response.usage.output_tokens
    )

    turn += 1

    final_block = next(
        block
        for block in critique_response.content
        if block.type == "tool_use"
    )

    final = FindingsSubmission.model_validate(
        final_block.input
    )

    traces.append(
        {
            "turn": turn,
            "role": "critique",
            "content": [
                block.model_dump(mode="json")
                for block in critique_response.content
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
