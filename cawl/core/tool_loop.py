"""
Shared tool execution loop.
Eliminates duplication between CLI, Shell, and UI tool loops.
"""

from cawl.tools.registry import get_tool


def run_tool_loop(
    client,
    messages: list,
    chat_history: list,
    max_iterations: int,
    streaming: bool = False,
    stream_callback=None,
    on_tool_call=None,
    on_tool_result=None,
    confirm_func=None,
    retry_check=None,
) -> str:
    iterations = 0
    while iterations < max_iterations:
        iterations += 1
        response = client.chat_with_tools(
            messages=messages, temperature=0.1,
            stream=streaming, stream_callback=stream_callback,
        )

        if not response["tool_calls"]:
            if response["content"]:
                if retry_check and retry_check(response["content"]):
                    messages.append({
                        "role": "system",
                        "content": (
                            "Tu respuesta anterior rechazó usar herramientas de forma incorrecta. "
                            "Tienes acceso real al proyecto activo y debes usar las herramientas "
                            "disponibles para inspeccionar archivos. "
                            "Vuelve a responder y usa una herramienta si corresponde."
                        ),
                    })
                    continue
                chat_history.append({"role": "assistant", "content": response["content"]})
            return response["content"]

        for tool_call in response["tool_calls"]:
            tool_name = tool_call["name"]
            tool_args = tool_call.get("arguments", {})

            if on_tool_call:
                on_tool_call(tool_name, tool_args)

            if tool_name == "run_command" and confirm_func:
                allowed, edited_args = confirm_func(tool_name, tool_args)
                if not allowed:
                    result_str = "Command execution denied by user."
                    messages.append({
                        "role": "user",
                        "content": f"RESULTADO de {tool_name}: {result_str}",
                    })
                    if on_tool_result:
                        on_tool_result(tool_name, result_str)
                    continue
                if edited_args:
                    tool_args = edited_args

            func = get_tool(tool_name)
            if func is None:
                result_str = f"[ERROR] Unknown tool: {tool_name}"
            else:
                try:
                    result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
                    result_str = str(result)
                except Exception as e:
                    result_str = f"[ERROR] Tool execution failed: {e}"

            if on_tool_result:
                on_tool_result(tool_name, result_str)

            messages.append({
                "role": "user",
                "content": f"RESULTADO de {tool_name}: {result_str}",
            })

    messages.append({
        "role": "system",
        "content": (
            "Has alcanzado el número máximo de llamadas a herramientas. "
            "Proporciona tu respuesta final basada en la información recopilada."
        ),
    })
    final = client.chat_with_tools(messages=messages, temperature=0.1)
    if final["content"]:
        chat_history.append({"role": "assistant", "content": final["content"]})
    return final["content"] or "[INFO] No se generó respuesta."
