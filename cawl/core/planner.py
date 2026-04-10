"""Planner module - decomposes a task description into actionable steps using LLM."""

import json
from cawl.core.llm_client import get_llm_client
from cawl.config.config import get_config
from cawl.tools.registry import TOOL_DESCRIPTIONS


def create_plan(task_text: str, memory_context: list = None) -> dict:
    """
    Create a plan from task text using LLM.

    Args:
        task_text: The task to decompose into steps.
        memory_context: Optional list of previous run summaries from ProjectMemory.

    Returns:
        dict with 'steps' list. Each step has: id, task, tools.
    """
    config = get_config()
    model = config.get("planner.model", "qwen2.5-coder:7b")
    client = get_llm_client()

    system_prompt = (
        "You are a professional task planner for an AI agent. "
        "Decompose the user task into a list of actionable steps that can be performed using tools.\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        "Each step must be a concise instruction. "
        "Return ONLY valid JSON with this structure: "
        '{"steps": [{"id": 1, "task": "description", "tools": ["tool_name"]}]}'
    )

    context_block = ""
    if memory_context:
        lines = ["Previous work in this project (for reference, avoid repeating):"]
        for run in memory_context:
            lines.append(f"- Task: {run.get('task', '')}")
            for s in run.get("steps", []):
                if s.get("action") not in ("error", "skipped"):
                    lines.append(
                        f"    [{s.get('tool', s.get('action'))}] {str(s.get('output', ''))[:120]}"
                    )
        context_block = "\n".join(lines)

    user_prompt = f"Task: {task_text}"
    if context_block:
        user_prompt = f"{context_block}\n\n{user_prompt}"

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    try:
        response_text = client.chat(model, messages, json_format=True)
        return json.loads(response_text)
    except Exception as e:
        print(f"[WARN] Error generating plan: {e}. Falling back to single-step plan.")
        return {
            "steps": [
                {"id": 1, "task": task_text.strip(), "tools": []},
            ]
        }
