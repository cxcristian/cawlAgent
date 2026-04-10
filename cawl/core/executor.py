"""Executor module - executes individual plan steps using tools."""

import json
import re
from cawl.tools.registry import get_tool, TOOLS, TOOL_DESCRIPTIONS
from cawl.core.llm_client import get_llm_client
from cawl.core.status import status
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


def execute_step(step: dict, task_text: str = None, previous_results: list = None) -> dict:
    """
    Execute a single plan step using LLM to decide on the action.

    Retries up to _MAX_JSON_RETRIES times when the model returns malformed JSON,
    feeding the parse error back so the model can self-correct.

    Args:
        step: Dict with 'id', 'task', and optionally 'tools'.
        task_text: Full original task description for context.
        previous_results: List of results from previous steps (for context).

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
        "If the step explicitly asks to write or create a file, use the write_file tool.\n"
        "If you call a tool, 'input' MUST be a dictionary of arguments.\n"
        "Return ONLY valid JSON — no markdown, no prose — with this exact structure:\n"
        '{"action": "tool_call | final_answer", "tool": "name", "input": {...}, "output": "explanation"}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
    ]

    if task_text:
        messages.append({
            "role": "user",
            "content": (
                "Original task description for context:\n"
                f"{task_text.strip()}\n\n"
                "Use this context when producing the result."
            ),
        })

    if previous_results:
        context_lines = ["PREVIOUS STEPS RESULTS:"]
        for i, res in enumerate(previous_results, start=1):
            action = res.get("action", "unknown")
            tool = res.get("tool", "<none>")
            tool_input = res.get("input", {})
            output = str(res.get("output", ""))[:500]
            context_lines.append(
                f"Step {i}: action={action}, tool={tool}, input={tool_input}, output={output}"
            )
        messages.append({
            "role": "user",
            "content": "\n".join(context_lines),
        })

    messages.append({"role": "user", "content": f"Step Task: {step.get('task')}"})

    res: dict = {}
    last_error: Exception = None

    for attempt in range(1 + _MAX_JSON_RETRIES):
        try:
            status.emit("thinking", "Analizando paso...")
            response_text = client.chat(messages=messages, json_format=True, timeout=600)
            clean = _extract_json(response_text)
            res = json.loads(clean)

            if "action" not in res:
                raise ValueError(f"Missing 'action' key. Got: {list(res.keys())}")
            break  # valid JSON — exit retry loop

        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            if attempt < _MAX_JSON_RETRIES:
                status.emit("retry", f"JSON inválido, reintento {attempt + 1}...")
                print(f"[WARN] Executor attempt {attempt + 1} returned invalid JSON: {e}. Retrying...")
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your previous response caused a JSON parse error: {e}\n"
                        "Return ONLY valid JSON matching the required structure. No extra text."
                    ),
                })
            else:
                status.emit("error", f"Executor fallido tras {1 + _MAX_JSON_RETRIES} intentos")
                return {
                    "action": "error",
                    "output": f"Executor failed after {1 + _MAX_JSON_RETRIES} attempts: {last_error}",
                }

        except Exception as e:
            status.emit("error", f"Error en executor: {e}")
            return {"action": "error", "output": f"Executor error: {e}"}

    # --- Dispatch the parsed action ---
    action = res.get("action")
    tool_name = res.get("tool") or (action if action in TOOLS else None)
    tool_input = res.get("input")

    def _write_output_file(path: str, content: str) -> dict:
        func = get_tool("write_file")
        args_preview = f"{{'path': '{path}', 'content': '<content>'}}"
        status.emit("tool_call", f"write_file({args_preview})")
        print(f"  [Action] Calling write_file with output to: {path}")
        try:
            result = func(path=path, content=content, mode="write")
        except Exception as e:
            status.emit("error", f"write_file lanzó excepción: {e}")
            return {"action": "error", "tool": "write_file", "input": {"path": path, "content": content}, "output": f"Tool raised: {e}"}
        preview = str(result)[:100].replace("\n", " ")
        status.emit("tool_result", f"write_file → {preview}")
        return {"action": "tool_call", "tool": "write_file", "input": {"path": path, "content": content}, "output": str(result)}

    # If the current step explicitly requires writing to a file and the model returned a final answer,
    # persist the answer content to the requested file automatically.
    if action == "final_answer":
        path_match = re.search(r"(?:write|escribir|crear).*?(?:file|archivo).*?([\w\-./\\]+\.md)", step.get("task", ""), re.IGNORECASE)
        if path_match:
            path = path_match.group(1).replace("`", "").strip()
            return _write_output_file(path, str(res.get("output", "")))

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

        args_preview = str(tool_input)[:80] + ("..." if str(tool_input).__len__() > 80 else "")
        status.emit("tool_call", f"{tool_name}({args_preview})")
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
            status.emit("error", f"{tool_name} lanzó excepción: {e}")
            return {"action": "error", "tool": tool_name, "input": tool_input, "output": f"Tool raised: {e}"}

        preview = str(result)[:100].replace("\n", " ")
        status.emit("tool_result", f"{tool_name} → {preview}")
        return {
            "action": "tool_call",
            "tool": tool_name,
            "input": tool_input,
            "output": str(result),
        }

    return res
