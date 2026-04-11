"""Executor module - executes individual plan steps using tools."""

import json
import re
import threading
from cawl.tools.registry import get_tool, TOOLS, TOOL_DESCRIPTIONS
from cawl.core.llm_client import get_llm_client
from cawl.core.status import status
from cawl.config.config import get_config

# Thread-safe 'always run' flag.
# Uses a Lock to protect read-modify-write cycles.
_always_run: bool = False
_always_run_lock = threading.Lock()


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


def _execute_inferred_tool(tool_name: str, tool_input: dict) -> dict:
    func = get_tool(tool_name)
    if func is None:
        return {"action": "error", "output": f"Tool '{tool_name}' not found."}

    args_preview = str(tool_input)[:80] + ("..." if len(str(tool_input)) > 80 else "")
    status.emit("tool_call", f"{tool_name}({args_preview})")
    print(f"  [Action] Calling inferred tool {tool_name} with input: {tool_input}")
    try:
        result = func(**tool_input)
    except Exception as e:
        status.emit("error", f"{tool_name} lanzó excepción: {e}")
        return {"action": "error", "tool": tool_name, "input": tool_input, "output": f"Tool raised: {e}"}
    preview = str(result)[:100].replace("\n", " ")
    status.emit("tool_result", f"{tool_name} → {preview}")
    return {"action": "tool_call", "tool": tool_name, "input": tool_input, "output": str(result)}


def reset_always_run() -> None:
    """Reset the session-wide 'always run' flag (call between sessions)."""
    global _always_run
    with _always_run_lock:
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
    with _always_run_lock:
        confirm_required = config.get("executor.confirm_commands", True) and not _always_run
    max_json_retries = config.get("executor.max_json_retries", 2)
    client = get_llm_client()

    system_prompt = (
        "You are an AI agent executor. Given a task step, decide whether to call a tool "
        "or provide a final answer.\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        "RULES:\n"
        "1. If the task asks to write, create, or save a file, you MUST use the write_file tool "
        "with the FULL content in the 'content' argument. NEVER just describe what you will do.\n"
        "2. 'output' in a final_answer should be a brief summary of what was accomplished — "
        "NOT the file content itself (that goes in write_file).\n"
        "3. NEVER say 'I will use...', 'To complete this...', 'Para completar...'. Just DO it.\n"
        "4. If you call a tool, 'input' MUST be a dictionary of arguments.\n"
        "5. Return ONLY valid JSON — no markdown, no prose — with this exact structure:\n"
        '{"action": "tool_call | final_answer", "tool": "name", "input": {...}, "output": "summary"}'
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

    for attempt in range(1 + max_json_retries):
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
            if attempt < max_json_retries:
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
                status.emit("error", f"Executor fallido tras {1 + max_json_retries} intentos")
                return {
                    "action": "error",
                    "output": f"Executor failed after {1 + max_json_retries} attempts: {last_error}",
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

    # Heuristic phrases that indicate the model is reasoning instead of producing content
    _META_COMMENT_PATTERNS = [
        r"(?i)(I will|voy a|para completar|para cumplir|voy a usar|usaré|usare)",
        r"(?i)(I need to|debo|tengo que|primero debo)",
        r"(?i)(I should|debería|sería mejor)",
        r"(?i)(in this step|en este paso|en este step)",
        r"(?i)(To complete|para completar|para finalizar|para terminar)",
    ]

    def _is_meta_comment(text: str) -> bool:
        """Check if text looks like reasoning instead of actual content."""
        text_lower = text.strip().lower()
        # If it's very short (< 100 chars) and mentions a tool name, it's likely meta
        if len(text_lower) < 100:
            for tool in ("write_file", "read_file", "grep_search", "glob_files"):
                if tool in text_lower:
                    return True
        for pattern in _META_COMMENT_PATTERNS:
            if re.search(pattern, text_lower):
                return True
        return False

    # If the current step requires writing to a file and the model returned a final answer,
    # validate the output content before auto-writing.
    # If it looks like meta-commentary, reject and force a retry with write_file tool.
    _auto_write_retries = 0
    _max_auto_write_retries = 3

    while action == "final_answer":
        path_match = re.search(
            r"(?:write|escribir|crear|generar|guardar).*?(?:file|archivo|reporte|report|archivo).*?([\w\-./\\]+\.\w+)",
            step.get("task", ""),
            re.IGNORECASE,
        )
        if not path_match:
            break  # No file-write task — proceed normally

        path = path_match.group(1).replace("`", "").strip()
        report_content = str(res.get("output", ""))

        if _is_meta_comment(report_content) and _auto_write_retries < _max_auto_write_retries:
            _auto_write_retries += 1
            status.emit("retry", f"Auto-write rechazado (razonamiento), reintento {_auto_write_retries}...")
            print(f"[WARN] Auto-write rejected: output looks like reasoning, not content. Retry {_auto_write_retries}/{_max_auto_write_retries}")
            messages.append({
                "role": "user",
                "content": (
                    f"ERROR: Your output was meta-commentary ('{report_content[:80]}...') instead of actual file content. "
                    f"You MUST use the write_file tool with the FULL content. "
                    f'DO NOT describe what you will do. Return JSON with: '
                    f'{{"action": "tool_call", "tool": "write_file", '
                    f'"input": {{"path": "{path}", "content": "FULL CONTENT HERE"}}}}'
                ),
            })
            # Re-query the LLM
            try:
                response_text = client.chat(messages=messages, json_format=True, timeout=600)
                clean = _extract_json(response_text)
                res = json.loads(clean)
                action = res.get("action")
                tool_name = res.get("tool") or (action if action in TOOLS else None)
                tool_input = res.get("input")
                continue  # Re-evaluate the new response
            except Exception as e:
                status.emit("error", f"Auto-write retry fallido: {e}")
                return {"action": "error", "output": f"Failed to write file after {_auto_write_retries} retries: {e}"}
        else:
            # Either content looks valid or max retries reached — write it
            if _is_meta_comment(report_content):
                status.emit("error", f"Auto-write: contenido parece razonamiento tras {_max_auto_write_retries} intentos")
                print(f"[WARN] Auto-write failed after {_max_auto_write_retries} retries. Output was: {report_content[:120]}")
                return {
                    "action": "error",
                    "output": (
                        f"Model returned reasoning instead of file content after {_max_auto_write_retries} retries. "
                        f"Please ensure the task uses write_file tool explicitly."
                    ),
                }
            return _write_output_file(path, report_content)

    if (action == "tool_call" or action in TOOLS) and tool_name:
        # Require confirmation for run_command unless user approved session-wide
        if tool_name == "run_command" and confirm_required:
            cmd = tool_input.get("command") if isinstance(tool_input, dict) else tool_input
            print(f"\n[CONFIRMATION REQUIRED] Agent wants to execute: {cmd}")
            choice = input("Authorize? (y)es / (a)lways / (n)o: ").lower()

            if choice == "a":
                with _always_run_lock:
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
