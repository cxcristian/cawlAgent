"""CawlShell - Interactive shell inspired by agentic terminal UX."""

import os
import sys
from pathlib import Path
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.styles import Style

from cawl.config.config import get_config, reload_config
from cawl.core.executor import clear_tool_cache
from cawl.core.llm_client import DEFAULT_MODEL, OllamaClient
from cawl.core.ollama_models import list_local_ollama_models, prompt_for_model_selection
from cawl.shell.completer import CawlCompleter
from cawl.shell.context import ShellContext
from cawl.shell.formatter import OutputFormatter
from cawl.tools.registry import TOOLS, TOOL_DESCRIPTIONS, get_tool

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
   CAWL
   Control & Action Web Loop
   Interactive terminal shell
"""

HELP_TEXT = """
Comandos:
  /help                Mostrar esta ayuda
  /status              Verificar Ollama y el modelo activo
  /session             Mostrar resumen de sesion
  /models              Listar modelos locales de Ollama
  /tools               Listar herramientas disponibles
  /verbose on|off      Activar o desactivar salida detallada
  /compact on|off      Activar o desactivar respuestas compactas
  /context             Ver archivos en contexto
  /add <file>          Agregar archivo al contexto
  /remove <file>       Quitar archivo del contexto
  /clear-context       Limpiar archivos del contexto
  /project <path>      Cambiar proyecto activo
  /model <name>        Cambiar modelo activo
  /model pick          Elegir modelo local de una lista
  /clear               Limpiar historial del chat
  /reset               Limpiar chat y contexto
  /quit /exit          Salir de la shell

Atajos:
  Enter                Enviar mensaje
  Ctrl+J               Insertar nueva linea
  Tab                  Auto-completar
  Up / Down            Navegar historial
"""


class CawlShell:
    """Interactive shell for CAWL agent with richer terminal controls."""

    MAX_TOOL_ITERATIONS = 20

    def __init__(self, project_path: str = ".", model: str = DEFAULT_MODEL):
        self.context = ShellContext(project_path=project_path, model=model)
        self.formatter = OutputFormatter(verbose=False)
        self.client: Optional[OllamaClient] = None
        self.chat_history: list[dict] = []
        self.system_prompt = self._build_system_prompt()

        hist_dir = os.path.expanduser("~/.cawl")
        os.makedirs(hist_dir, exist_ok=True)
        self.hist_file = os.path.join(hist_dir, "shell_history")
        self.key_bindings = self._build_key_bindings()

        from cawl.core.confirmation import initialize_confirmation_from_config
        initialize_confirmation_from_config()

    def _build_system_prompt(self) -> str:
        return (
            "Eres CAWL, un asistente local de desarrollo enfocado en codigo limpio, estructurado y eficiente.\n\n"
            "DIRECTRICES PRINCIPALES:\n"
            "- EJECUCION DETERMINISTA: sigue las instrucciones con precision.\n"
            "- SIN ALUCINACION: responde solo con informacion verificada o derivada del contexto.\n"
            "- SALIDA ESTRUCTURADA: tus respuestas deben ser claras, concretas y utiles.\n"
            "- ENFOQUE EN INGENIERIA: prioriza mantenibilidad, legibilidad, seguridad y rendimiento razonable.\n"
            "- USA LAS HERRAMIENTAS DISPONIBLES: Tienes acceso a herramientas para "
            "interactuar con el sistema de archivos. Usalas para leer, escribir, buscar "
            "y explorar. No inventes contenido de archivos, leelos con las herramientas.\n"
            f"\n{self.context.get_context_prompt()}\n"
            "ESTILO DE RESPUESTA:\n"
            "- Responde SIEMPRE en espanol.\n"
            "- Usa un tono profesional, claro y colaborativo.\n"
            "- Cuando entregues codigo, favorece implementaciones completas y listas para usar.\n\n"
            "HERRAMIENTAS DISPONIBLES:\n"
            "Para usar una herramienta, responde UNICAMENTE con un bloque JSON:\n\n"
            "```json\n"
            '{"name": "nombre_herramienta", "arguments": {"arg1": "valor1"}}\n'
            "```\n\n"
            "NO agregues texto adicional cuando uses una herramienta. SOLO el JSON.\n\n"
            f"Lista de herramientas:\n{TOOL_DESCRIPTIONS}\n\n"
            "REGLAS DE USO:\n"
            "1. Una herramienta a la vez. Espera el resultado antes de continuar.\n"
            "2. Usa paths absolutos siempre que sea posible.\n"
            "3. Cuando tengas toda la informacion, responde normalmente en espanol.\n"
            "4. NUNCA digas 'voy a usar' antes del JSON. SOLO el JSON.\n"
        )

    def initialize(self) -> bool:
        """Initialize connection to Ollama and verify model."""
        print(self.formatter.format_note("Conexion", f"Conectando a Ollama con {self.context.model}..."))
        try:
            self.client = OllamaClient(model=self.context.model)
            if not self.client.verify_model():
                print(self.formatter.format_error(f"Modelo '{self.context.model}' no encontrado. Usa cawl pull."))
                return False
            print(self.formatter.format_note("Conexion", "Ollama listo."))
            return True
        except ConnectionError as e:
            print(self.formatter.format_error(str(e)))
            return False

    def run(self):
        """Run the interactive shell loop."""
        print(BANNER)
        self._print_session_header()

        session = PromptSession(
            history=FileHistory(self.hist_file),
            auto_suggest=AutoSuggestFromHistory(),
            completer=CawlCompleter(self.context, list(TOOLS.keys())),
            style=SHELL_STYLE,
            key_bindings=self.key_bindings,
            multiline=False,
            complete_while_typing=True,
        )

        while True:
            try:
                user_input = session.prompt(
                    self._build_prompt(),
                    bottom_toolbar=self._build_toolbar,
                ).strip()
                if not user_input:
                    continue
                if user_input.startswith("/"):
                    self._handle_command(user_input)
                    continue
                if not self.client:
                    print(self.formatter.format_error("No hay conexion activa. Usa /status."))
                    continue
                self._execute_tool_loop(user_input)
            except (KeyboardInterrupt, EOFError):
                print("\n" + self.formatter.format_note("Salida", "Sesion cerrada."))
                break
            except Exception as e:
                print(self.formatter.format_error(str(e)))

    def _build_prompt(self):
        """Build the context-aware prompt display."""
        ctx_files = len(self.context.context_files)
        project_name = Path(self.context.project_path).name or self.context.project_path
        return HTML(
            f'<prompt>cawl</prompt><context-bar> [{project_name} | {self.context.model} | ctx:{ctx_files}]</context-bar><prompt>&gt; </prompt>'
        )

    def _build_toolbar(self):
        """Build a bottom toolbar with quick controls."""
        verbose = "verbose:on" if self.formatter.verbose else "verbose:off"
        compact = "compact:on" if self.formatter.compact else "compact:off"
        return HTML(
            f"<context-bar> Enter enviar | Ctrl+J nueva linea | /session resumen | {verbose} | {compact} </context-bar>"
        )

    def _build_key_bindings(self):
        """Create key bindings for a more modern shell feel."""
        bindings = KeyBindings()

        @bindings.add("c-j")
        def _(event):
            event.current_buffer.insert_text("\n")

        return bindings

    def _print_session_header(self):
        models = list_local_ollama_models()
        print(self.formatter.format_note(
            "Terminal de desarrollo",
            (
                f"Proyecto: {self.context.project_path}\n"
                f"Modelo activo: {self.context.model}\n"
                f"Modelos locales: {len(models)}\n"
                "Usa /help para comandos y /session para ver el estado actual."
            ),
        ))
        print()

    def _handle_command(self, cmd: str):
        """Handle slash commands."""
        raw_parts = cmd.strip().split(maxsplit=1)
        command = raw_parts[0].lower()
        arg = raw_parts[1] if len(raw_parts) > 1 else None

        if command in ("/quit", "/exit"):
            print(self.formatter.format_note("Salida", "Sesion finalizada."))
            sys.exit(0)
        if command == "/help":
            print(HELP_TEXT)
        elif command == "/status":
            self._cmd_status()
        elif command == "/session":
            self._cmd_session()
        elif command == "/models":
            self._cmd_models()
        elif command == "/tools":
            print("\n" + self.formatter.format_note("Herramientas", TOOL_DESCRIPTIONS) + "\n")
        elif command == "/verbose":
            self._cmd_toggle("verbose", arg)
        elif command == "/compact":
            self._cmd_toggle("compact", arg)
        elif command == "/context":
            self._cmd_context()
        elif command == "/add":
            self._cmd_add(arg)
        elif command == "/remove":
            self._cmd_remove(arg)
        elif command == "/clear-context":
            count = self.context.clear_files()
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Contexto", f"Archivos removidos: {count}."))
        elif command == "/project":
            self._cmd_project(arg)
        elif command == "/model":
            self._cmd_model(arg)
        elif command == "/clear":
            self.chat_history.clear()
            print(self.formatter.format_note("Chat", "Historial del chat limpiado."))
        elif command == "/reset":
            self.chat_history.clear()
            count = self.context.clear_files()
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Reset", f"Sesion reiniciada. Archivos removidos: {count}."))
        else:
            print(self.formatter.format_error(f"Comando desconocido: {command}. Usa /help."))

    def _cmd_toggle(self, target: str, arg: Optional[str]):
        value = None
        if arg in ("on", "true", "1"):
            value = True
        elif arg in ("off", "false", "0"):
            value = False

        if target == "verbose":
            if value is None:
                state = "ON" if self.formatter.verbose else "OFF"
                print(self.formatter.format_note("Verbose", f"Estado actual: {state}"))
            else:
                self.formatter.verbose = value
                print(self.formatter.format_note("Verbose", f"Modo detallado {'activado' if value else 'desactivado'}"))
        elif target == "compact":
            if value is None:
                state = "ON" if self.formatter.compact else "OFF"
                print(self.formatter.format_note("Compacto", f"Estado actual: {state}"))
            else:
                self.formatter.compact = value
                print(self.formatter.format_note("Compacto", f"Modo compacto {'activado' if value else 'desactivado'}"))

    def _cmd_status(self):
        try:
            client = OllamaClient(model=self.context.model)
            available = client.verify_model()
            body = (
                f"Ollama: Connected\n"
                f"Model: {self.context.model}\n"
                f"Available: {'Yes' if available else 'No'}"
            )
            if not available:
                body += "\nPull with: cawl pull"
            print("\n" + self.formatter.format_note("Estado", body) + "\n")
        except ConnectionError as e:
            print("\n" + self.formatter.format_error(f"Ollama no conectado. {e}") + "\n")

    def _cmd_session(self):
        print("\n" + self.formatter.format_session_summary(
            project_path=self.context.project_path,
            model=self.context.model,
            context_files=len(self.context.context_files),
            message_count=len(self.chat_history),
            verbose=self.formatter.verbose,
            compact=self.formatter.compact,
        ) + "\n")

    def _cmd_models(self):
        models = list_local_ollama_models()
        if not models:
            print(self.formatter.format_error("No se pudieron listar modelos locales de Ollama."))
            return
        print("\n" + self.formatter._line("note", "Modelos locales:"))
        for index, model in enumerate(models, start=1):
            marker = " <- activo" if model == self.context.model else ""
            print(f"    {index}. {model}{marker}")
        print()

    def _cmd_context(self):
        if not self.context.context_files:
            print(self.formatter.format_note("Contexto", "No hay archivos en contexto."))
        else:
            print("\n" + self.formatter._line("note", "Archivos en contexto:"))
            for item in self.context.context_files:
                print(f"    - {item}")
            print()

    def _cmd_add(self, path: Optional[str]):
        if not path:
            print(self.formatter.format_error("Uso: /add <file_path>"))
            return
        resolved = self.context.add_file(path)
        if resolved:
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Contexto", f"Archivo agregado: {resolved}"))
        else:
            print(self.formatter.format_error(f"Archivo no encontrado: {path}"))

    def _cmd_remove(self, path: Optional[str]):
        if not path:
            print(self.formatter.format_error("Uso: /remove <file_path>"))
            return
        if self.context.remove_file(path):
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Contexto", f"Archivo removido: {path}"))
        else:
            print(self.formatter.format_error(f"Archivo no presente en contexto: {path}"))

    def _cmd_project(self, path: Optional[str]):
        if not path:
            print(self.formatter.format_note("Proyecto", f"Actual: {self.context.project_path}"))
            return
        resolved = self.context.set_project(path)
        if os.path.exists(resolved):
            os.chdir(resolved)
            reload_config(project_path=resolved)
            clear_tool_cache()
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Proyecto", f"Proyecto cambiado a: {resolved}"))
        else:
            print(self.formatter.format_error(f"Ruta no encontrada: {path}"))

    def _cmd_model(self, name: Optional[str]):
        if not name:
            print(self.formatter.format_note("Modelo", f"Actual: {self.context.model}"))
            return
        selected_name = name
        if name.strip().lower() == "pick":
            selected_name = prompt_for_model_selection(default_model=self.context.model)
            if not selected_name:
                print(self.formatter.format_error("No hay modelos locales disponibles para seleccionar."))
                return
        try:
            self.client = OllamaClient(model=selected_name)
            self.context.model = selected_name
            self.system_prompt = self._build_system_prompt()
            print(self.formatter.format_note("Modelo", f"Modelo cambiado a: {selected_name}"))
        except ConnectionError as e:
            print(self.formatter.format_error(f"No se pudo conectar con el modelo '{selected_name}': {e}"))

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
                response = self.client.chat_with_tools(messages=messages, temperature=0.1)
            except Exception as e:
                print(self.formatter.format_error(str(e)))
                return

            if not response["tool_calls"]:
                if response["content"]:
                    self.chat_history.append({"role": "assistant", "content": response["content"]})
                    print("\n" + self.formatter.format_response(response["content"]))
                    print("\n" + self.formatter.format_note("Tiempo", self.formatter.elapsed()) + "\n")
                return

            for tool_call in response["tool_calls"]:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})
                print(self.formatter.format_tool_call(tool_name, tool_args))

                if tool_name == "run_command":
                    from cawl.core.confirmation import ConfirmationResponse, confirm_command_shell

                    cmd = tool_args.get("command", str(tool_args))
                    working_dir = tool_args.get("working_dir")
                    timeout = get_config().get("executor.command_timeout", 60)

                    response_type, edited_command = confirm_command_shell(
                        cmd,
                        working_dir=working_dir,
                        timeout=timeout,
                        state=None,
                    )
                    if response_type == ConfirmationResponse.NO:
                        result_str = "Command execution denied by user."
                        print(self.formatter.format_note("Comando omitido", result_str))
                        messages.append({"role": "user", "content": f"RESULTADO de {tool_name}: {result_str}"})
                        continue
                    if response_type == ConfirmationResponse.EDIT and edited_command:
                        tool_args["command"] = edited_command
                        print(self.formatter.format_note("Comando editado", edited_command))

                func = get_tool(tool_name)
                if func is None:
                    result_str = f"[ERROR] Unknown tool: {tool_name}"
                else:
                    try:
                        result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
                        result_str = str(result)
                    except Exception as e:
                        result_str = f"[ERROR] Tool execution failed: {e}"

                print(self.formatter.format_tool_result(tool_name, result_str))
                messages.append({"role": "user", "content": f"RESULTADO de {tool_name}: {result_str}"})

        messages.append({
            "role": "system",
            "content": (
                "Has alcanzado el numero maximo de llamadas a herramientas. "
                "Proporciona tu respuesta final basada en la informacion recopilada."
            ),
        })
        try:
            final = self.client.chat_with_tools(messages=messages, temperature=0.1)
            if final["content"]:
                self.chat_history.append({"role": "assistant", "content": final["content"]})
                print("\n" + self.formatter.format_response(final["content"]))
        except Exception as e:
            print(self.formatter.format_error(str(e)))

        print("\n" + self.formatter.format_note("Iteraciones maximas", self.formatter.elapsed()) + "\n")
