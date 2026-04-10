"""Planner module - decomposes a task description into actionable steps using LLM."""

import json
import re
from cawl.core.llm_client import get_llm_client
from cawl.core.status import status
from cawl.tools.registry import TOOL_DESCRIPTIONS

# Max retries when the model returns invalid JSON
_MAX_JSON_RETRIES = 2


def _extract_json(text: str) -> str:
    """
    Try to extract a JSON object from a string that may contain prose.
    Handles markdown code fences and inline JSON blobs.
    """
    # Strip markdown code fences
    fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if fence:
        return fence.group(1).strip()
    # Find first {...} block
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        return brace.group(0)
    return text.strip()


def create_plan(task_text: str, memory_context: list = None) -> dict:
    """
    Create a plan from task text using LLM.

    Retries up to _MAX_JSON_RETRIES times if the model returns malformed JSON,
    feeding the parse error back as context so the model can self-correct.

    Args:
        task_text: The task to decompose into steps.
        memory_context: Optional list of previous run summaries from ProjectMemory.

    Returns:
        dict with 'steps' list. Each step has: id, task, tools.
    """
    client = get_llm_client()

    system_prompt = (
        "You are a professional task planner for an AI agent. "
        "Decompose the user task into a list of actionable steps that can be performed using tools.\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        "Each step must be a concise instruction. "
        "Return ONLY valid JSON — no markdown, no prose — with this exact structure:\n"
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

    last_error: Exception = None

    status.emit("planning", "Generando plan de ejecución...")

    for attempt in range(1 + _MAX_JSON_RETRIES):
        try:
            response_text = client.chat(messages=messages, json_format=True)
            clean = _extract_json(response_text)
            plan = json.loads(clean)

            # Basic schema validation
            if "steps" not in plan or not isinstance(plan["steps"], list):
                raise ValueError(f"Missing or invalid 'steps' key. Got: {list(plan.keys())}")

            status.emit("planning", f"Plan listo: {len(plan['steps'])} paso(s)")
            return plan

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < _MAX_JSON_RETRIES:
                status.emit("retry", f"JSON inválido en intento {attempt + 1}, reintentando...")
                print(f"[WARN] Plan attempt {attempt + 1} returned invalid JSON: {e}. Retrying...")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous response caused a JSON parse error: {e}\n"
                        "Return ONLY valid JSON matching the required structure. No extra text."
                    ),
                })
            else:
                status.emit("error", f"Plan fallido tras {1 + _MAX_JSON_RETRIES} intentos")
                print(
                    f"[WARN] All {1 + _MAX_JSON_RETRIES} plan attempts failed ({last_error}). "
                    "Falling back to single-step plan."
                )

        except Exception as e:
            last_error = e
            status.emit("error", f"Error inesperado en planner: {e}")
            print(f"[WARN] Unexpected error generating plan: {e}. Falling back.")
            break

    return {
        "steps": [
            {"id": 1, "task": task_text.strip(), "tools": []},
        ]
    }
