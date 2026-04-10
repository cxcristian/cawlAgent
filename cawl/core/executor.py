"""Executor module - executes individual plan steps using tools."""

import json
import re
from cawl.tools.registry import get_tool, TOOLS, TOOL_DESCRIPTIONS
from cawl.core.llm_client import get_llm_client
from cawl.config.config import get_config

# Session-level flag: user chose "always run" for this execution.
# NOTE: module-level global intentionally kept simple for single-threaded use.
# For multi-threaded scenarios, pass as a mutable container or use threading.local().
_always_run: bool = False

# Max retries when the model returns invalid JSON
_MAX_JSON_RETRIES = 2


def _extract_json(text: str) -> str:
    """
    Extract a JSON object from text that may contain prose or markdown fences.
    """
    fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
    if fence:
        return fence.group(1).strip()
    brace = re.search(r"\{[\s\S]*\}", text)
    if brace:
        return brace.group(0)
    return text.strip()


def reset_always_run() -> None:
    """Reset the session-wide 'always run' flag (call between sessions)."""
    global _always_run
    _always_run = False


def execute_step(step: dict) -> dict:
    """
    Execute a single plan step using LLM to decide on the action.

    Retries up to _MAX_JSON_RETRIES times when the model returns malformed JSON,
    feeding the parse error back so the model can self-correct.

    Args:
        step: Dict with 'id', 'task', and optionally 'tools'.

    Returns:
        Dict with 'action', 'tool', 'input', 'output'.
    """
    global _always_run
    config = get_config()
    confirm_required = config.get("executor.confirm_commands", True)
    client = get_llm_client()

    system_prompt = (
        "You are an AI agent executor. Given a task step, decide whether to call a tool "
        "or provide a final answer.\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        "If you call a tool, 'input' MUST be a dictionary of arguments.\n"
        "Return ONLY valid JSON — no markdown, no prose — with this exact structure:\n"
        '{"action": "tool_call | final_answer", "tool": "name", "input": {...}, "output": "explanation"}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Step Task: {step.get('task')}"},
    ]

    res: dict = {}
    last_error: Exception = None

    for attempt in range(1 + _MAX_JSON_RETRIES):
        try:
            response_text = client.chat(messages=messages, json_format=True)
            clean = _extract_json(response_text)
            res = json.loads(clean)

            if "action" not in res:
                raise ValueError(f"Missing 'action' key. Got: {list(res.keys())}")
            break  # valid JSON — exit retry loop

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < _MAX_JSON_RETRIES:
                print(f"[WARN] Executor attempt {attempt + 1} returned invalid JSON: {e}. Retrying...")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous response caused a JSON parse error: {e}\n"
                        "Return ONLY valid JSON matching the required structure. No extra text."
                    ),
                })
            else:
                return {
                    "action": "error",
                    "output": f"Executor failed after {1 + _MAX_JSON_RETRIES} attempts: {last_error}",
                }

        except Exception as e:
            return {"action": "error", "output": f"Executor error: {e}"}

    # --- Dispatch the parsed action ---
    action = res.get("action")
    tool_name = res.get("tool") or (action if action in TOOLS else None)
    tool_input = res.get("input")

    if (action == "tool_call" or action in TOOLS) and tool_name:
        # Require confirmation for run_command unless user approved session-wide
        if tool_name == "run_command" and confirm_required and not _always_run:
            cmd = tool_input.get("command") if isinstance(tool_input, dict) else tool_input
            print(f"\n[CONFIRMATION REQUIRED] Agent wants to execute: {cmd}")
            choice = input("Authorize? (y)es / (a)lways / (n)o: ").lower()

            if choice == "a":
                _always_run = True
            elif choice != "y":
                return {"action": "skipped", "output": "Command execution denied by user."}

        func = get_tool(tool_name)
        if func is None:
            return {"action": "error", "output": f"Tool '{tool_name}' not found."}

        print(f"  [Action] Calling {tool_name} with input: {tool_input}")

        try:
            if isinstance(tool_input, dict):
                result = func(**tool_input)
            elif isinstance(tool_input, list):
                result = func(*tool_input)
            elif tool_input:
                result = func(tool_input)
            else:
                result = func()
        except Exception as e:
            return {"action": "error", "tool": tool_name, "input": tool_input, "output": f"Tool raised: {e}"}

        return {
            "action": "tool_call",
            "tool": tool_name,
            "input": tool_input,
            "output": str(result),
        }

    return res
