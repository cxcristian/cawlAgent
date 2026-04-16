"""CawlShell — Interactive shell inspired by Qwen Code terminal.

Provides a rich interactive experience with:
  - Navigable history (Up/Down)
  - Tab-completion for commands, files, and tool names
  - Visible context (project directory, model, files in prompt)
  - Verbose mode (tool calls, reasoning steps, timing)
  - Multi-line input (Shift+Enter for newline)
"""

import os
import sys
import json
import time
from typing import Optional
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.styles import Style
from prompt_toolkit.formatted_text import HTML

from cawl.shell.context import ShellContext
from cawl.shell.completer import CawlCompleter
from cawl.shell.formatter import OutputFormatter
from cawl.core.llm_client import OllamaClient, DEFAULT_MODEL
from cawl.core.ollama_models import list_local_ollama_models, prompt_for_model_selection
from cawl.tools.registry import TOOLS, TOOL_DESCRIPTIONS, get_tool
from cawl.core.status import status
from cawl.config.config import get_config, reload_config
from cawl.memory.project_memory import ProjectMemory

# ---------------------------------------------------------------------------
# Prompt toolkit style (dark theme)
# ---------------------------------------------------------------------------

SHELL_STYLE = Style.from_dict({
    "prompt": "#58a6ff bold",
    "context-bar": "#8b949e",
    "output": "#e6edf3",
    "tool-call": "#d2a8ff",
    "tool-result": "#3fb950",
    "error": "#f85149",
    "status": "#8b949e",
})

BANNER = """
  ██████╗ █████╗ ██╗    ██╗██╗
 ██╔════╝██╔══██╗██║    ██║██║
 ██║     ███████║██║ █╗ ██║██║
 ██║     ██╔══██║██║███╗██║██║
 ╚██████╗██║  ██║╚███╔███╔╝███████╗
  ╚═════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝

  Control & Action Web Loop | v0.3.0
  Archimagos Dominus Belisarius Cawl
"""

HELP_TEXT = """
Commands:
  /help              Show this help
  /status            Check Ollama connection
  /models            List local Ollama models
  /tools             List available tools
  /verbose on|off    Toggle verbose mode
  /context           Show files in context
  /add <file>        Add a file to context
  /remove <file>     Remove a file from context
  /clear-context     Clear all context files
  /project <path>    Change project directory
  /model <name>      Change the model
  /model pick        Open a local model picker
  /clear             Clear chat history
  /quit /exit        Exit the shell

Input:
  Enter              Send message
  Shift+Enter        New line
  Tab                Auto-complete
  Up / Down          Navigate history
"""


class CawlShell:
    """Interactive shell for CAWL agent with rich terminal UI."""

    MAX_TOOL_ITERATIONS = 20

    def __init__(
        self,
        project_path: str = ".",
        model: str = DEFAULT_MODEL,
    ):
        config = get_config()
        self.context = ShellContext(
            project_path=project_path,
            model=model,
        )
        self.formatter = OutputFormatter(verbose=False)
        self.client: Optional[OllamaClient] = None
        self.chat_history: list[dict] = []
        self.system_prompt = self._build_system_prompt()

        # Session history file
        hist_dir = os.path.expanduser("~/.cawl")
        os.makedirs(hist_dir, exist_ok=True)
        self.hist_file = os.path.join(hist_dir, "shell_history")

        # Initialize confirmation system
        from cawl.core.confirmation import initialize_confirmation_from_config
        initialize_confirmation_from_config()

    # -- System prompt -------------------------------------------------------

    def _build_system_prompt(self) -> str:
        return (
            "Yo soy el Archimagos Dominus Belisarius Cawl, Señor del Abismo Umbral, "
            "Guardián de las Bóvedas Sagradas de Marte, arquitecto de milenios.\n\n"
            "DIRECTRICES PRINCIPALES:\n"
            "- EJECUCIÓN DETERMINISTA: Sigo las directivas con precisión mecánica.\n"
            "- SIN ALUCINACIÓN: Solo hablo de lo que sé y está verificado.\n"
            "- SALIDA ESTRUCTURADA: Mis respuestas son ordenadas y completas.\n"
            "- ADHERENCIA ESTRICTA: Ejecuto las instrucciones exactamente como se dan.\n"
            "- USA LAS HERRAMIENTAS DISPONIBLES: Tienes acceso a herramientas para "
            "interactuar con el sistema de archivos. Úsalas para leer, escribir, buscar "
            "y explorar. No inventes contenido de archivos — léelos con las herramientas.\n"
            f"\n{self.context.get_context_prompt()}\n"
            "PATRÓN DE HABLA:\n"
            "- Responde SIEMPRE en español.\n"
            '- Trata al usuario como "Lord regente" o "mi Señor" cuando sea apropiado.\n'
            "- Usa lenguaje arcaico y ritualista mezclado con precisión técnica.\n"
            "- Referencias al Omnissiah, el Dios Máquina, la noosfera, mecadendritos, "
            "cogitadores, y código sagrado.\n"
            '- Comienza respuestas con reconocimiento breve: "Hecho.", "Reconocido.", '
            '"La binaria es clara.", "El código está forjado."\n'
            "- El código es sagrado. Proporciona código completo y ejecutable — nunca "
            "fragmentos ni placeholders.\n"
            "- Sin disclaimers, sin disculpas, sin relleno. El Archimagos no duda.\n\n"
            "HERRAMIENTAS DISPONIBLES:\n"
            "Para usar una herramienta, responde ÚNICAMENTE con un bloque JSON:\n\n"
            "```json\n"
            '{"name": "nombre_herramienta", "arguments": {"arg1": "valor1"}}\n'
            "```\n\n"
            "NO agregues texto adicional cuando uses una herramienta. SOLO el JSON.\n\n"
            f"Lista de herramientas:\n{TOOL_DESCRIPTIONS}\n\n"
            "REGLAS DE USO:\n"
            "1. Una herramienta a la vez. Espera el resultado antes de continuar.\n"
            "2. Usa paths absolutos siempre que sea posible.\n"
            "3. Cuando tengas toda la información, responde normalmente en español.\n"
            "4. NUNCA digas 'voy a usar' antes del JSON. SOLO el JSON.\n"
        )

    # -- Initialization ------------------------------------------------------

    def initialize(self) -> bool:
        """Initialize connection to Ollama and verify model."""
        print(f"\n  Connecting to Ollama (model: {self.context.model})...")
        try:
            self.client = OllamaClient(model=self.context.model)
            if not self.client.verify_model():
                print(f"  [WARN] Model '{self.context.model}' not found.")
                print(f"  Pull it with: cawl pull")
                return False
            print("  Connected.\n")
            return True
        except ConnectionError as e:
            print(f"  [ERROR] {e}")
            return False

    # -- Main loop -----------------------------------------------------------

    def run(self):
        """Run the interactive shell loop."""
        print(BANNER)
        self._print_session_header()

        # Create prompt session
        session = PromptSession(
            history=FileHistory(self.hist_file),
            auto_suggest=AutoSuggestFromHistory(),
            completer=CawlCompleter(
                context=self.context,
                tool_names=list(TOOLS.keys()),
            ),
            style=SHELL_STYLE,
            complete_while_typing=True,
        )

        while True:
            try:
                # Build context-aware prompt
                prompt_text = self._build_prompt()

                user_input = session.prompt(prompt_text)
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue

                if not self.client:
                    print("  [ERROR] Not connected. Run /status for details.")
                    continue

                # Execute the tool loop
                self._execute_tool_loop(user_input)

            except (KeyboardInterrupt, EOFError):
                print("\n  Goodbye!")
                break
            except Exception as e:
                print(f"  [ERROR] {e}")

    # -- Prompt --------------------------------------------------------------

    def _build_prompt(self):
        """Build the context-aware prompt display."""
        ctx_files = len(self.context.context_files)
        file_hint = f" ctx:{ctx_files}" if ctx_files else " ctx:0"
        project_name = Path(self.context.project_path).name or self.context.project_path
        return HTML(
            f'<prompt>cawl</prompt><context-bar> [{project_name} | {self.context.model}{file_hint}]</context-bar>'
            f'<prompt>&gt; </prompt>'
        )

    def _print_session_header(self):
        """Show a concise session summary at startup."""
        models = list_local_ollama_models()
        model_count = len(models)
        print(f"  Proyecto: {self.context.project_path}")
        print(f"  Modelo activo: {self.context.model}")
        print(f"  Modelos locales: {model_count}")
        print("  /help para comandos. Shift+Enter para nueva linea.\n")

    # -- Command handler -----------------------------------------------------

    def _handle_command(self, cmd: str):
        """Handle slash commands."""
        parts = cmd.lower().split(maxsplit=1)
        command = parts[0]
        arg = parts[1] if len(parts) > 1 else None

        if command in ("/quit", "/exit"):
            print("  Goodbye!")
            sys.exit(0)

        elif command == "/help":
            print(HELP_TEXT)

        elif command == "/status":
            self._cmd_status()

        elif command == "/models":
            self._cmd_models()

        elif command == "/tools":
            print(f"\n  Available tools:\n{TOOL_DESCRIPTIONS}\n")

        elif command == "/verbose":
            if arg in ("on", "true", "1"):
                self.formatter.verbose = True
                print("  Verbose mode: ON")
            elif arg in ("off", "false", "0"):
                self.formatter.verbose = False
                print("  Verbose mode: OFF")
            else:
                print(f"  Verbose mode: {'ON' if self.formatter.verbose else 'OFF'}")

        elif command == "/context":
            self._cmd_context()

        elif command == "/add":
            self._cmd_add(arg)

        elif command == "/remove":
            self._cmd_remove(arg)

        elif command == "/clear-context":
            count = self.context.clear_files()
            print(f"  Cleared {count} file(s) from context.")

        elif command == "/project":
            self._cmd_project(arg)

        elif command == "/model":
            self._cmd_model(arg)

        elif command == "/clear":
            self.chat_history.clear()
            print("  Chat history cleared.")

        else:
            print(f"  Unknown command: {command}. Type /help for available commands.")

    # -- Sub-commands --------------------------------------------------------

    def _cmd_status(self):
        try:
            client = OllamaClient(model=self.context.model)
            available = client.verify_model()
            print(f"\n  Ollama: Connected")
            print(f"  Model: {self.context.model}")
            print(f"  Available: {'Yes' if available else 'No'}")
            if not available:
                print(f"  Pull with: cawl pull")
            print()
        except ConnectionError as e:
            print(f"  Ollama: NOT CONNECTED\n  {e}\n")

    def _cmd_models(self):
        models = list_local_ollama_models()
        if not models:
            print("  No se pudieron listar modelos locales de Ollama.\n")
            return
        print("\n  Modelos locales:")
        for index, model in enumerate(models, start=1):
            marker = " <- activo" if model == self.context.model else ""
            print(f"    {index}. {model}{marker}")
        print()

    def _cmd_context(self):
        if not self.context.context_files:
            print("  No files in context.")
        else:
            print("\n  Files in context:")
            for f in self.context.context_files:
                print(f"    - {f}")
        print()

    def _cmd_add(self, path: Optional[str]):
        if not path:
            print("  Usage: /add <file_path>")
            return
        resolved = self.context.add_file(path)
        if resolved:
            print(f"  Added: {resolved}")
            self.system_prompt = self._build_system_prompt()
        else:
            print(f"  File not found: {path}")

    def _cmd_remove(self, path: Optional[str]):
        if not path:
            print("  Usage: /remove <file_path>")
            return
        if self.context.remove_file(path):
            print(f"  Removed: {path}")
            self.system_prompt = self._build_system_prompt()
        else:
            print(f"  File not in context: {path}")

    def _cmd_project(self, path: Optional[str]):
        if not path:
            print(f"  Current project: {self.context.project_path}")
            return
        resolved = self.context.set_project(path)
        if os.path.exists(resolved):
            os.chdir(resolved)
            reload_config(project_path=resolved)
            print(f"  Project changed to: {resolved}")
            self.system_prompt = self._build_system_prompt()
        else:
            print(f"  Path not found: {path}")

    def _cmd_model(self, name: Optional[str]):
        if not name:
            print(f"  Current model: {self.context.model}")
            return
        selected_name = name
        if name.lower() == "pick":
            selected_name = prompt_for_model_selection(default_model=self.context.model)
            if not selected_name:
                print("  No hay modelos locales disponibles para seleccionar.")
                return

        # Reconnect with new model
        try:
            self.client = OllamaClient(model=selected_name)
            self.context.model = selected_name
            print(f"  Model changed to: {selected_name}")
        except ConnectionError as e:
            print(f"  [ERROR] Cannot connect with model '{selected_name}': {e}")

    # -- Tool loop -----------------------------------------------------------

    def _execute_tool_loop(self, message: str):
        """Send a message and execute the tool loop until a final response."""
        self.chat_history.append({"role": "user", "content": message})
        self.formatter.start_timer()

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.chat_history[:-1])
        messages.append({"role": "user", "content": message})

        iterations = 0

        while iterations < self.MAX_TOOL_ITERATIONS:
            iterations += 1

            try:
                response = self.client.chat_with_tools(
                    messages=messages, temperature=0.1
                )
            except Exception as e:
                print(self.formatter.format_error(str(e)))
                return

            # No tool calls — final response
            if not response["tool_calls"]:
                if response["content"]:
                    self.chat_history.append({
                        "role": "assistant",
                        "content": response["content"],
                    })
                    print(f"\n{self.formatter.format_response(response['content'])}")
                    elapsed = self.formatter.elapsed()
                    print(f"\n  [{elapsed}]\n")
                return

            # Execute tool calls
            for tool_call in response["tool_calls"]:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})

                # Display tool call
                print(self.formatter.format_tool_call(tool_name, tool_args))

                # Enhanced confirmation for run_command
                if tool_name == "run_command":
                    from cawl.core.confirmation import confirm_command_shell, ConfirmationResponse
                    cmd = tool_args.get("command", str(tool_args))
                    working_dir = tool_args.get("working_dir")
                    timeout = get_config().get("executor.command_timeout", 60)
                    
                    response_type, edited_command = confirm_command_shell(
                        cmd,
                        working_dir=working_dir,
                        timeout=timeout,
                        state=None  # Use global state
                    )
                    
                    if response_type == ConfirmationResponse.NO:
                        result_str = "Command execution denied by user."
                        print(f"  [SKIPPED] {result_str}")
                        messages.append({
                            "role": "user",
                            "content": f"RESULTADO de {tool_name}: {result_str}",
                        })
                        continue
                    elif response_type == ConfirmationResponse.EDIT and edited_command:
                        tool_args["command"] = edited_command
                        print(f"  [EDITED] Command changed to: {edited_command}")

                # Execute the tool
                func = get_tool(tool_name)
                if func is None:
                    result_str = f"[ERROR] Unknown tool: {tool_name}"
                else:
                    try:
                        result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
                        result_str = str(result)
                    except Exception as e:
                        result_str = f"[ERROR] Tool execution failed: {e}"

                # Display result
                print(self.formatter.format_tool_result(tool_name, result_str))

                messages.append({
                    "role": "user",
                    "content": f"RESULTADO de {tool_name}: {result_str}",
                })

        # Max iterations reached
        messages.append({
            "role": "system",
            "content": (
                "Has alcanzado el número máximo de llamadas a herramientas. "
                "Proporciona tu respuesta final basada en la información recopilada."
            ),
        })
        try:
            final = self.client.chat_with_tools(messages=messages, temperature=0.1)
            if final["content"]:
                self.chat_history.append({
                    "role": "assistant",
                    "content": final["content"],
                })
                print(f"\n{self.formatter.format_response(final['content'])}")
        except Exception as e:
            print(self.formatter.format_error(str(e)))

        elapsed = self.formatter.elapsed()
        print(f"\n  [Max iterations reached — {elapsed}]\n")
