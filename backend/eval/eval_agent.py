import json
from pathlib import Path

import sys
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.agent import client, MODEL, SYSTEM_PROMPT, GATHER_TOOLS, SUBMIT_FINDINGS_TOOL, build_diff_summary, MAX_GATHER_TURNS
from app.schemas import FindingsSubmission
from app.retrieval import search_code


def execute_tool_local(repo_dir: Path, db, repo_id: int, tool_name: str, tool_input: dict) -> str:
    if tool_name == "read_file":
        try:
            return (repo_dir / tool_input["file_path"]).read_text(encoding="utf-8", errors="ignore")[:8000]
        except Exception as e:
            return f"Error reading file: {e}"
    if tool_name in ("search_codebase", "get_related_tests"):
        query = tool_input.get("query") or f"test file for {tool_input.get('file_path', '')}"
        return json.dumps(search_code(db, repo_id, query, top_k=5))
    return f"Unknown tool: {tool_name}"


def run_agent_review_local(
    db, repo_dir: Path, repo_id: int, pr_data: dict, files: list[dict],
    use_retrieval: bool = True, use_critique: bool = True,
):
    diff_summary = build_diff_summary(files)
    messages = [{
        "role": "user",
        "content": f"Review this pull request.\n\nTitle: {pr_data['title']}\nDescription: {pr_data.get('body') or '(none)'}\n\nChanged files:\n\n{diff_summary}",
    }]

    tools = GATHER_TOOLS if use_retrieval else [SUBMIT_FINDINGS_TOOL]
    turn, draft = 0, None

    while turn < MAX_GATHER_TURNS:
        turn += 1
        response = client.messages.create(model=MODEL, max_tokens=4096, system=SYSTEM_PROMPT, tools=tools, messages=messages)
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            messages.append({"role": "user", "content": "Please call submit_findings when ready."})
            continue

        tool_results, submitted_input = [], None
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "submit_findings":
                submitted_input = block.input
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": "Draft received."})
            else:
                result = execute_tool_local(repo_dir, db, repo_id, block.name, block.input)
                tool_results.append({"type": "tool_result", "tool_use_id": block.id, "content": result})
        messages.append({"role": "user", "content": tool_results})

        if submitted_input is not None:
            draft = FindingsSubmission.model_validate(submitted_input)
            break

    if draft is None:
        raise RuntimeError("No draft produced within max turns")

    if not use_critique:
        return draft

    critique_messages = messages + [{
        "role": "user",
        "content": "Critique your draft findings for false positives/duplicates/nitpicks, then call submit_findings again with your final list.",
    }]
    critique_response = client.messages.create(
        model=MODEL, max_tokens=4096, system=SYSTEM_PROMPT,
        tools=[SUBMIT_FINDINGS_TOOL], tool_choice={"type": "tool", "name": "submit_findings"},
        messages=critique_messages,
    )
    final_block = next(b for b in critique_response.content if b.type == "tool_use")
    return FindingsSubmission.model_validate(final_block.input)