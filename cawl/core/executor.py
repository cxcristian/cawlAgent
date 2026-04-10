"""Executor module - executes individual plan steps using tools."""

import json
from cawl.tools.registry import get_tool, TOOLS, TOOL_DESCRIPTIONS
from cawl.core.llm_client import get_llm_client
from cawl.config.config import get_config

# Session-level flag: user chose "always run" for this execution
ALWAYS_RUN = False


def execute_step(step: dict) -> dict:
    """
    Execute a single plan step using LLM to decide on the action.

    Args:
        step: Dict with 'id', 'task', and optionally 'tools'.

    Returns:
        Dict with 'action', 'tool', 'input', 'output'.
    """
    global ALWAYS_RUN
    config = get_config()
    model = config.get("executor.model", "qwen2.5-coder:7b")
    confirm_required = config.get("executor.confirm_commands", True)
    client = get_llm_client()

    system_prompt = (
        "You are an AI agent executor. Given a task step, decide whether to call a tool "
        "or provide a final answer.\n"
        f"Available tools:\n{TOOL_DESCRIPTIONS}\n\n"
        "If you call a tool, 'input' MUST be a dictionary of arguments.\n"
        "Return ONLY valid JSON with this structure:\n"
        '{"action": "tool_call | final_answer", "tool": "name", "input": {...}, "output": "explanation"}'
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Step Task: {step.get('task')}"},
    ]

    try:
        response_text = client.chat(model, messages, json_format=True)
        res = json.loads(response_text)

        action = res.get("action")
        tool_name = res.get("tool") or (action if action in TOOLS else None)
        tool_input = res.get("input")

        if (action == "tool_call" or action in TOOLS) and tool_name:
            # Require confirmation for run_command unless user approved session-wide
            if tool_name == "run_command" and confirm_required and not ALWAYS_RUN:
                cmd = tool_input.get("command") if isinstance(tool_input, dict) else tool_input
                print(f"\n[CONFIRMATION REQUIRED] Agent wants to execute: {cmd}")
                choice = input("Authorize? (y)es / (a)lways / (n)o: ").lower()

                if choice == "a":
                    ALWAYS_RUN = True
                elif choice != "y":
                    return {"action": "skipped", "output": "Command execution denied by user."}

            func = get_tool(tool_name)
            if func is None:
                return {"action": "error", "output": f"Tool '{tool_name}' not found."}

            print(f"  [Action] Calling {tool_name} with input: {tool_input}")

            if isinstance(tool_input, dict):
                result = func(**tool_input)
            elif isinstance(tool_input, list):
                result = func(*tool_input)
            elif tool_input:
                result = func(tool_input)
            else:
                result = func()

            return {
                "action": "tool_call",
                "tool": tool_name,
                "input": tool_input,
                "output": str(result),
            }

        return res

    except Exception as e:
        return {"action": "error", "output": f"Executor error: {e}"}
