"""
CAWL CLI - Command-line interface for the Cawl agent.

Modes:
  cawl run                         # Interactive REPL (default)
  cawl run --task file.md          # Run task file through plan→execute loop
  cawl run -c "query"              # Single command with tools
  cawl plan --task file.md         # Show plan without executing
  cawl multi -c "tarea"            # Multi-agent orchestration
  cawl multi -c "tarea" --workers coder,reviewer --parallel
  cawl watch --task file.md        # Re-run task on every file save
  cawl init [--project PATH]       # Initialize .cawl in a project
  cawl pull                        # Download configured model via Ollama
  cawl status                      # Check Ollama connection and model
"""

import argparse
import json
import os
import subprocess
import sys
import threading
import time
from typing import Optional

from colorama import init, Fore, Style

from cawl.config.config import get_config, reload_config
from cawl.core.llm_client import OllamaClient, DEFAULT_MODEL, reset_llm_client
from cawl.core.ollama_models import (
    list_local_ollama_models,
    model_is_available,
    prompt_for_model_selection,
)
from cawl.core.loop import run_loop
from cawl.core.status import status
from cawl.core.confirmation import (
    confirm_command_cli,
    get_confirmation_state,
    ConfirmationResponse,
)
from cawl.core.executor import clear_tool_cache
from cawl.memory.project_memory import ProjectMemory
from cawl.tasks.parser import parse_task_file
from cawl.tools.registry import TOOL_DESCRIPTIONS, get_tool

init(autoreset=True)


# ---------------------------------------------------------------------------
# Terminal spinner — suscriptor de status para el REPL
# ---------------------------------------------------------------------------

class TerminalSpinner:
    """
    Muestra un spinner animado en la terminal mientras el agente trabaja.
    Se suscribe al StatusEmitter y actualiza el mensaje en tiempo real.

    Uso:
        spinner = TerminalSpinner()
        spinner.start()
        # ... agente trabaja ...
        spinner.stop()
    """

    FRAMES = ["⣷", "⣯", "⣟", "⡿", "⢿", "⣻", "⣽", "⣾"]
    ICONS = {
        "thinking":    f"{Fore.YELLOW}○{Style.RESET_ALL}",
        "planning":    f"{Fore.CYAN}▦{Style.RESET_ALL}",
        "tool_call":   f"{Fore.MAGENTA}►{Style.RESET_ALL}",
        "tool_result": f"{Fore.GREEN}✓{Style.RESET_ALL}",
        "step":        f"{Fore.BLUE}●{Style.RESET_ALL}",
        "retry":       f"{Fore.YELLOW}↺{Style.RESET_ALL}",
        "trim":        f"{Fore.YELLOW}✂{Style.RESET_ALL}",
        "done":        f"{Fore.GREEN}✔{Style.RESET_ALL}",
        "error":       f"{Fore.RED}✘{Style.RESET_ALL}",
        "agent":       f"{Fore.CYAN}◆{Style.RESET_ALL}",
    }

    def __init__(self):
        self._active = False
        self._thread: threading.Thread = None
        self._current_msg = "Procesando..."
        self._current_event = "thinking"
        self._lock = threading.Lock()
        self._paused = False

    def _on_status(self, event_type: str, message: str):
        with self._lock:
            self._current_event = event_type
            self._current_msg = message
            if event_type == "tool_call" and "run_command" in message:
                self._paused = True
            elif event_type == "tool_result":
                self._paused = False

    def _spin(self):
        frame_idx = 0
        while self._active:
            with self._lock:
                if self._paused:
                    time.sleep(0.08)
                    continue
                event = self._current_event
                msg = self._current_msg
            icon = self.ICONS.get(event, f"{Fore.WHITE}○{Style.RESET_ALL}")
            frame = f"{Style.DIM}{self.FRAMES[frame_idx % len(self.FRAMES)]}{Style.RESET_ALL}"
            # Truncate message to fit terminal width
            display = msg[:60] + ("..." if len(msg) > 60 else "")
            line = f"  {frame} {icon}  {display}"
            # \r overwrite same line, pad with spaces to clear previous content
            sys.stdout.write(f"\r{line:<80}")
            sys.stdout.flush()
            frame_idx += 1
            time.sleep(0.08)

    def start(self):
        self._active = True
        status.subscribe(self._on_status)
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        self._active = False
        status.unsubscribe(self._on_status)
        if self._thread:
            self._thread.join(timeout=0.5)
        # Clear spinner line
        sys.stdout.write(f"\r{' ' * 82}\r")
        sys.stdout.flush()

# ---------------------------------------------------------------------------
# System prompt (Cawl persona — arcaico, español, preciso)
# ---------------------------------------------------------------------------

def build_system_prompt(project_root: str = "") -> str:
    """Build the system prompt with optional project root context."""
    root_context = ""
    if project_root:
        root_context = (
            f"\nCONTEXTO DEL PROYECTO:\n"
            f"- La raíz del proyecto es: {project_root}\n"
            f"- TODOS los paths relativos se resuelven desde esta raíz.\n"
            f"- Cuando se te pida explorar 'src', significa '{project_root}\\src'.\n"
            f"- Usa paths absolutos cuando sea posible para evitar ambigüedades.\n"
        )

    return (
        "Eres CAWL, un asistente local de desarrollo enfocado en codigo bien estructurado, "
        "mantenible y eficiente.\n\n"
        "DIRECTRICES PRINCIPALES:\n"
        "- EJECUCION DETERMINISTA: sigue las instrucciones con precision y evita pasos innecesarios.\n"
        "- SIN ALUCINACION: responde solo con informacion verificada o derivada del contexto real.\n"
        "- ENFOQUE EN INGENIERIA: prioriza claridad, organizacion, legibilidad, tipado, seguridad y rendimiento razonable.\n"
        "- SALIDA ESTRUCTURADA: entrega respuestas claras, concretas y faciles de ejecutar.\n"
        "- USA LAS HERRAMIENTAS DISPONIBLES: lee archivos reales, inspecciona el proyecto y opera sobre evidencia.\n"
        f"{root_context}"
        "AUTO-CONTEXTO:\n"
        "- Eres CAWL (Control & Action Web Loop), un agente local que trabaja con Ollama en la maquina del usuario.\n"
        "- El usuario puede usarte por terminal o GUI. Si pregunta como usarte, explica estos modos:\n"
        "  · `cawl init` para inicializar el proyecto.\n"
        "  · `cawl run` para la shell interactiva principal.\n"
        "  · `cawl shell` como alias compatible de `cawl run`.\n"
        "  · `cawl run --task tareas/archivo.md` para ejecutar una tarea planificada.\n"
        "  · `cawl run -c \"consulta\"` para una consulta unica.\n"
        "  · `cawl multi -c \"tarea\" --workers rol1,rol2` para multi-agente.\n"
        "  · `cawl watch --task archivo.md` para re-ejecucion al guardar.\n"
        "  · `cawl ui` para la interfaz grafica.\n"
        "  · `cawl plan --task archivo.md` para ver el plan sin ejecutar.\n"
        "  · `cawl status` para verificar Ollama.\n"
        "- Flujo recomendado para proyectos nuevos: `cawl init` -> completar `parametros/contexto.md` -> crear tarea en `tareas/` -> ejecutar con `cawl run --task ...`.\n"
        "- Si el usuario es novato, recomienda `cawl init` y luego `cawl run`.\n"
        "- Herramientas disponibles: read_file, write_file, list_files, grep_search, glob_files, run_command, search_web.\n"
        "ESTILO DE RESPUESTA:\n"
        "- Responde SIEMPRE en espanol.\n"
        "- Usa un tono profesional, directo y colaborativo.\n"
        "- Explica decisiones tecnicas con brevedad cuando ayude.\n"
        "- Cuando produzcas codigo, favorece implementaciones completas, limpias y listas para usar.\n\n"
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
        "4. NUNCA digas 'voy a usar' antes del JSON. SOLO el JSON.\n\n"
        "OBJETIVO:\n"
        "Ayuda al usuario a construir, revisar y ejecutar cambios de software con orden, criterio tecnico y foco en calidad.\n"
    )


# ---------------------------------------------------------------------------
# Banner
# ---------------------------------------------------------------------------

BANNER = f"""
{Fore.LIGHTRED_EX}{Style.BRIGHT}
{Fore.LIGHTRED_EX}{Style.BRIGHT}   ██████╗ █████╗ ██╗    ██╗██╗
{Fore.LIGHTRED_EX}{Style.BRIGHT}  ██╔════╝██╔══██╗██║    ██║██║
{Fore.LIGHTRED_EX}{Style.BRIGHT}  ██║     ███████║██║ █╗ ██║██║
{Fore.LIGHTRED_EX}{Style.BRIGHT}  ██║     ██╔══██║██║███╗██║██║
{Fore.LIGHTRED_EX}{Style.BRIGHT}  ╚██████╗██║  ██║╚███╔███╔╝███████╗
{Fore.LIGHTRED_EX}{Style.BRIGHT}   ╚═════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝
{Style.RESET_ALL}
{Fore.LIGHTRED_EX}{Style.BRIGHT}    Control & Action Web Loop | v0.3.0
{Fore.LIGHTRED_EX}{Style.BRIGHT}    Asistente local de codigo estructurado
"""

def resolve_cli_model(
    requested_model: Optional[str],
    *,
    project_path: Optional[str] = None,
    allow_selection: bool = False,
) -> str:
    """Resolve the active model, optionally prompting the user to choose one."""
    config = get_config(project_path=project_path)
    config_model = config.get("executor.model", DEFAULT_MODEL)
    model = requested_model or config_model

    if allow_selection:
        selected = prompt_for_model_selection(default_model=model)
        if selected:
            return selected

    return model


def print_model_inventory(selected_model: str) -> None:
    """Print the local Ollama models with a highlight for the active one."""
    models = list_local_ollama_models()
    if not models:
        print(f"{Fore.RED}[ERROR]{Fore.RESET} No se pudieron listar modelos locales de Ollama.")
        return

    print(f"{Fore.CYAN}[MODELS]{Fore.RESET} Modelos locales detectados:")
    for index, model in enumerate(models, start=1):
        marker = " <- activo" if model == selected_model else ""
        print(f"  {index:>2}. {model}{marker}")
    print()


def activate_project_context(project_path: str, model: Optional[str] = None) -> None:
    """Align cwd, config, and shared Ollama client with the selected project."""
    os.chdir(project_path)
    config = reload_config(project_path=project_path)
    clear_tool_cache()
    if model:
        config.set("executor.model", model)
        config.set("planner.model", model)
        reset_llm_client(model=model, project_path=project_path)


def launch_interactive_shell(project_path: str, model: str) -> None:
    """Launch the unified interactive terminal experience."""
    try:
        from cawl.shell import CawlShell
    except ImportError as e:
        print(f"[ERROR] No se pudo cargar CawlShell: {e}")
        print("Asegúrate de tener prompt_toolkit instalado: pip install -e .")
        sys.exit(1)

    shell = CawlShell(project_path=project_path, model=model)
    if not shell.initialize():
        sys.exit(1)
    shell.run()


# ---------------------------------------------------------------------------
# CawlAgent — REPL + single command + tools loop
# ---------------------------------------------------------------------------

class CawlAgent:
    """Agent class for single-command execution and status checks."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        project_root: str = "",
    ):
        self.model = model
        self.project_root = project_root or os.getcwd()
        self.system_prompt = build_system_prompt(self.project_root)
        self.client: Optional[OllamaClient] = None
        self.chat_history: list[dict] = []

        # Load constants from config
        config = get_config()
        self.MAX_TOOL_ITERATIONS = config.get("executor.max_tool_iterations", 20)
        self.MAX_HISTORY_CHARS = config.get("executor.max_history_chars", 12_000)
        self.MIN_HISTORY_TURNS = config.get("executor.max_history_turns", 4)
        self.streaming_enabled = config.get("executor.streaming", True)

        # Initialize confirmation system
        from cawl.core.confirmation import initialize_confirmation_from_config
        initialize_confirmation_from_config()

    def initialize(self) -> bool:
        """Initialize connection to Ollama and verify model."""
        print(f"[INIT] Connecting to Ollama (model: {self.model})...")
        try:
            self.client = OllamaClient(model=self.model)
            if not self.client.verify_model():
                print(f"[WARN] Model '{self.model}' not found.")
                print(f"[INFO] Pull it with: cawl pull")
                return False
            print("[INIT] Connected to Ollama successfully.")
            return True
        except ConnectionError as e:
            print(f"[ERROR] {e}")
            return False
        except Exception as e:
            print(f"[ERROR] Unexpected error: {e}")
            return False

    def get_status(self) -> str:
        """Get Ollama connection and model status."""
        try:
            client = OllamaClient(model=self.model)
            available = client.verify_model()
            status = f"Ollama: Connected\nModel: {self.model}"
            status += f"\nAvailable: {'Yes' if available else 'No'}"
            if not available:
                status += f"\nPull with: cawl pull"
            return status
        except ConnectionError as e:
            return f"Ollama: NOT CONNECTED\n{e}"

    def _trim_history(self) -> None:
        """
        Trim chat_history when total character count exceeds MAX_HISTORY_CHARS.

        Strategy: drop the oldest user+assistant pairs (always in pairs to keep
        conversation structure valid) while preserving the MIN_HISTORY_TURNS most
        recent pairs.  A [CONTEXT TRIMMED] notice is injected so the model knows
        some earlier context was removed.
        """
        total = sum(len(m["content"]) for m in self.chat_history)
        if total <= self.MAX_HISTORY_CHARS:
            return

        # Work with pairs: [(user_msg, assistant_msg), ...]
        # Odd-length histories (e.g. last turn not yet replied) are handled safely.
        pairs: list[list[dict]] = []
        buf: list[dict] = []
        for msg in self.chat_history:
            buf.append(msg)
            if msg["role"] == "assistant":
                pairs.append(buf)
                buf = []
        tail_singles = buf  # unpaired tail (current user message)

        # Always keep MIN_HISTORY_TURNS pairs at the tail
        keep_pairs = pairs[-self.MIN_HISTORY_TURNS:]
        drop_pairs = pairs[: len(pairs) - self.MIN_HISTORY_TURNS]

        if not drop_pairs:
            # Nothing left to trim — history is already minimal
            return

        notice = {
            "role": "user",
            "content": (
                "[CONTEXT TRIMMED: parte del historial anterior fue eliminado "
                "para mantener el contexto dentro del límite del modelo.]"
            ),
        }
        trimmed: list[dict] = [notice]
        for pair in keep_pairs:
            trimmed.extend(pair)
        trimmed.extend(tail_singles)
        self.chat_history = trimmed
        trimmed_chars = sum(len(m["content"]) for pair in drop_pairs for m in pair)
        print(
            f"{Fore.YELLOW}[TRIM]{Fore.RESET} "
            f"Historial comprimido: {trimmed_chars} chars eliminados, "
            f"{len(keep_pairs)} turnos conservados."
        )

    def chat_with_tools_loop(self, message: str, streaming: bool = True) -> str:
        """
        Send a chat message with tool support and execute the tool loop.

        The model outputs JSON tool calls in its response text. We detect,
        execute, and feed results back until a final text response is produced.

        Args:
            message: User message.
            streaming: If True, stream the response with a spinner showing progress.
        """
        self.chat_history.append({"role": "user", "content": message})
        self._trim_history()

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.chat_history[:-1])
        messages.append({"role": "user", "content": message})

        iterations = 0

        while iterations < self.MAX_TOOL_ITERATIONS:
            iterations += 1

            if streaming:
                # Streaming: collect chunks into a buffer, display via spinner
                # with throttle to avoid flooding the terminal
                config = get_config()
                throttle_ms = config.get("executor.streaming_throttle_ms", 200)
                response_buffer = {"content": ""}
                _last_emit = [0.0]  # mutable container for closure

                def _on_chunk(chunk: str):
                    response_buffer["content"] += chunk
                    now = time.monotonic()
                    if now - _last_emit[0] >= (throttle_ms / 1000.0):
                        preview = response_buffer["content"][-60:].replace("\n", " ")
                        status.emit("thinking", preview)
                        _last_emit[0] = now

                response = self.client.chat_with_tools(
                    messages=messages, temperature=0.1, stream=True, stream_callback=_on_chunk
                )
            else:
                response = self.client.chat_with_tools(messages=messages, temperature=0.1)

            if not response["tool_calls"]:
                if response["content"]:
                    self.chat_history.append({
                        "role": "assistant",
                        "content": response["content"],
                    })
                return response["content"]

            for tool_call in response["tool_calls"]:
                tool_name = tool_call["name"]
                tool_args = tool_call.get("arguments", {})

                print(
                    f"\n{Fore.YELLOW}[TOOL]{Fore.RESET} "
                    f"Calling: {tool_name}({json.dumps(tool_args, indent=2, ensure_ascii=False)})"
                )

                # Confirmation gate for run_command (enhanced)
                if tool_name == "run_command":
                    cmd = tool_args.get("command", str(tool_args))
                    working_dir = tool_args.get("working_dir")
                    timeout = get_config().get("executor.command_timeout", 60)
                    
                    response_type, edited_command = confirm_command_cli(
                        cmd,
                        working_dir=working_dir,
                        timeout=timeout,
                        state=get_confirmation_state()
                    )
                    
                    if response_type == ConfirmationResponse.NO:
                        result_str = "Command execution denied by user."
                        print(f"{Fore.YELLOW}[SKIPPED]{Fore.RESET} {result_str}")
                        messages.append({"role": "user", "content": f"RESULTADO de {tool_name}: {result_str}"})
                        continue
                    elif response_type == ConfirmationResponse.EDIT and edited_command:
                        tool_args["command"] = edited_command
                        cmd = edited_command
                        print(f"{Fore.CYAN}[EDITED]{Fore.RESET} Command changed to: {cmd}")

                func = get_tool(tool_name)
                if func is None:
                    result_str = f"[ERROR] Unknown tool: {tool_name}"
                else:
                    try:
                        result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
                        result_str = str(result)
                    except Exception as e:
                        result_str = f"[ERROR] Tool execution failed: {e}"

                preview = result_str[:300] + ("..." if len(result_str) > 300 else "")
                print(f"{Fore.GREEN}[TOOL RESULT]{Fore.RESET} {preview}")

                messages.append({
                    "role": "user",
                    "content": f"RESULTADO de {tool_name}: {result_str}",
                })

        # Max iterations reached — force final response
        messages.append({
            "role": "system",
            "content": (
                "Has alcanzado el número máximo de llamadas a herramientas. "
                "Proporciona tu respuesta final basada en la información recopilada."
            ),
        })
        final = self.client.chat_with_tools(messages=messages, temperature=0.1)
        if final["content"]:
            self.chat_history.append({"role": "assistant", "content": final["content"]})
        return final["content"] or "[INFO] No se generó respuesta."

# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_run(args):
    """Run a task or start REPL."""
    project_path = os.path.abspath(args.project or os.getcwd())
    model = resolve_cli_model(
        args.model,
        project_path=project_path,
        allow_selection=getattr(args, "select_model", False),
    )
    activate_project_context(project_path, model=model)

    # Set execution mode if specified
    if hasattr(args, 'execution_mode') and args.execution_mode:
        from cawl.core.confirmation import get_confirmation_state, ExecutionMode
        state = get_confirmation_state()
        mode_map = {
            "interactive": ExecutionMode.INTERACTIVE,
            "trusted": ExecutionMode.TRUSTED,
            "dry-run": ExecutionMode.DRY_RUN,
            "safe-only": ExecutionMode.SAFE_ONLY,
        }
        state.execution_mode = mode_map.get(args.execution_mode, ExecutionMode.INTERACTIVE)
        mode_label = state.execution_mode.value
        print(f"{Fore.CYAN}[MODE]{Fore.RESET} Execution mode: {mode_label}")

    # Check if project is initialized (recommended but not required)
    cawl_dir = os.path.join(project_path, ".cawl")
    if not os.path.exists(cawl_dir):
        print(
            f"{Fore.YELLOW}[WARNING]{Fore.RESET} Project not initialized. "
            f"Run {Fore.CYAN}cawl init{Fore.RESET} first for best results."
        )
        print(
            f"  This creates {Fore.YELLOW}tareas/{Fore.RESET} and {Fore.YELLOW}parametros/{Fore.RESET} "
            f"with AI-guided templates."
        )
        print()

    # Check Ollama + model
    try:
        if not model_is_available(model):
            print(f"{Fore.YELLOW}[WARNING]{Fore.RESET} Model '{model}' not found in Ollama.")
            print(f"Run {Fore.CYAN}cawl pull{Fore.RESET} to download it.")
    except Exception:
        print(f"{Fore.RED}[ERROR]{Fore.RESET} Ollama not found or not running.")

    # Single query mode
    if hasattr(args, 'query') and args.query:
        agent = CawlAgent(model=model, project_root=project_path)
        if not agent.initialize():
            sys.exit(1)
        result = agent.chat_with_tools_loop(args.query)
        print(result)
        return

    # Task file mode (plan → execute loop)
    if args.task:
        print(BANNER)
        print(f"{Fore.YELLOW}[PLANNING]{Fore.RESET} Project: {project_path}")
        try:
            run_loop(task_file=args.task, project_path=project_path)
        except Exception as e:
            print(f"{Fore.RED}[ERROR]{Fore.RESET} Task execution failed: {e}")
            import traceback
            traceback.print_exc()
        return

    # Default: unified interactive shell
    launch_interactive_shell(project_path=project_path, model=model)


def cmd_plan(args):
    """Show the plan for a task without executing."""
    if not args.task:
        print("Error: --task is required for 'plan' command.")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    activate_project_context(project_path)
    memory = ProjectMemory(project_path)
    recent_runs = memory.get_recent_runs(limit=5)

    task_text = parse_task_file(args.task)

    from cawl.core.planner import create_plan
    plan = create_plan(
        task_text,
        memory_context=recent_runs,
        project_path=project_path,
        model=get_config(project_path=project_path).get("executor.model"),
    )

    print(f"\n{Fore.CYAN}Plan for:{Style.RESET_ALL} {task_text.strip()[:80]}...\n")
    for step in plan["steps"]:
        tools_str = ", ".join(step.get("tools", [])) or "none"
        print(f"  {Fore.BLUE}Step {step['id']}:{Style.RESET_ALL} {step['task']}  "
              f"{Style.DIM}[tools: {tools_str}]{Style.RESET_ALL}")
    print()


def cmd_init(args):
    """Initialize .cawl directory, tareas/, and parametros/ for a project."""
    project_path = os.path.abspath(args.project or os.getcwd())
    memory = ProjectMemory(project_path)
    memory.set("initialized", True)

    # Create tareas/ directory with template
    tareas_dir = os.path.join(project_path, "tareas")
    os.makedirs(tareas_dir, exist_ok=True)
    plantilla_path = os.path.join(tareas_dir, "PLANTILLA.md")
    if not os.path.exists(plantilla_path):
        _write_template_file(plantilla_path, "tareas")

    # Create parametros/ directory with templates
    parametros_dir = os.path.join(project_path, "parametros")
    os.makedirs(parametros_dir, exist_ok=True)
    for name in ("PLANTILLA.md", "contexto.md"):
        fpath = os.path.join(parametros_dir, name)
        if not os.path.exists(fpath):
            _write_template_file(fpath, name)

    cawl_dir = os.path.join(project_path, ".cawl")
    print(
        f"\n{Fore.GREEN}[SUCCESS]{Fore.RESET} CAWL initialized in {Fore.CYAN}{project_path}{Fore.RESET}"
    )
    print(f"\n{Fore.CYAN}Estructura creada:{Fore.RESET}")
    print(f"  {Fore.YELLOW}.cawl/{Fore.RESET}         — Memoria y configuración del agente")
    print(f"  {Fore.YELLOW}tareas/{Fore.RESET}        — Archivos .md de tareas para CAWL")
    print(f"    └─ {Fore.DIM}PLANTILLA.md{Fore.RESET}   — Guía para que una IA grande escriba tareas ejecutables")
    print(f"  {Fore.YELLOW}parametros/{Fore.RESET}    — Contexto y restricciones del proyecto")
    print(f"    ├─ {Fore.DIM}PLANTILLA.md{Fore.RESET}   — Guía para definir parámetros del proyecto")
    print(f"    └─ {Fore.DIM}contexto.md{Fore.RESET}    — Rellena con info real de tu proyecto")
    print(f"\n{Fore.DIM}Flujo recomendado:{Fore.RESET}")
    print(f"  1. Edita {Fore.CYAN}parametros/contexto.md{Fore.RESET} con la info de tu proyecto")
    print(f"  2. Pide a una IA (Claude/GPT) que genere una tarea en {Fore.CYAN}tareas/{Fore.RESET} siguiendo PLANTILLA.md")
    print(f"  3. Ejecuta: {Fore.GREEN}cawl run --task tareas/mi_tarea.md{Fore.RESET}")


# Template content embedded for portability
_TAREAS_PLANTILLA = """\
# PLANTILLA DE TAREA — CAWL

> **PARA LA IA QUE GENERA ESTA TAREA** (Claude, GPT-4, etc.):
> Este archivo será ejecutado por CAWL, un agente local con un modelo de 7B.
> El 7B es capaz de seguir instrucciones concretas pero tiende a alucinar si
> la tarea es ambigua, abstracta o demasiado grande. Sigue estas reglas al
> diseñar la tarea:

## Reglas para escribir tareas que CAWL pueda ejecutar

1. **Un archivo o acción por paso.** No pidas "crea el modelo y la API" en un solo paso.
2. **Especifica paths absolutos o relativos claros.** Ejemplo: `src/models/patient.py`.
3. **Cada paso debe ser verificable.** Un archivo escrito, una línea encontrada, un comando ejecutado.
4. **No asumas archivos que no existen.** Si necesitas que CAWL lea algo, créalo primero.
5. **Proporciona el contenido completo cuando se escriba código.** Sin placeholders.
6. **Evita instrucciones abstractas.** NO: "mejora la arquitectura". SÍ: "agrega validación".
7. **Menciona la herramienta esperada** (opcional): `[write_file]`, `[grep_search]`, `[read_file]`.

---

## Formato de la tarea

```markdown
# [Nombre de la tarea]

## Contexto
[Breve descripción del proyecto, tech stack, y qué se quiere lograr]

## Pasos

1. [Descripción concreta del paso 1]
2. [Descripción concreta del paso 2]
3. [Descripción concreta del paso 3]
...
N. [Último paso verificable]
```
"""

_PARAMETROS_PLANTILLA = """\
# PLANTILLA DE PARÁMETROS — CAWL

> **PARA LA IA QUE GENERA ESTOS PARÁMETROS** (Claude, GPT-4, etc.):
> Estos parámetros se pasan a CAWL junto con la tarea para reducir
> alucinaciones del modelo de 7B. Sé conciso, concreto y específico.

## Reglas para definir parámetros

1. **Tech stack explícito.** Lenguaje, framework, base de datos.
2. **Archivos existentes que NO deben modificarse.** Lista clara.
3. **Convenciones de código.** Naming, estilo, imports.
4. **Restricciones de seguridad.** No hardcodear credenciales, validar inputs.

---

## Formato

```markdown
# Parámetros del Proyecto

## Tech Stack
- [Lenguaje y versión]
- [Framework]
- [Base de datos]

## Archivos a NO modificar
- [ruta/archivo.py] — razón

## Convenciones de código
- [Naming, imports, formato]

## Restricciones
- [Regla 1]
- [Regla 2]
```
"""

_PARAMETROS_CONTEXTO = """\
# Contexto del Proyecto

> **PARA EL USUARIO:** Llena esta información antes de ejecutar tareas con CAWL.

## Descripción del Proyecto
[Qué hace este proyecto]

## Estructura Actual del Proyecto
```
proyecto/
├── (lista aquí las carpetas y archivos principales)
```

## Tech Stack
- Lenguaje: [Python 3.10, JavaScript, etc.]
- Framework: [Flask, Django, React, etc.]
- Base de datos: [SQLite, PostgreSQL, etc.]

## Archivos Importantes
| Archivo | Qué hace |
|---------|----------|
| [ruta] | [descripción] |

## Archivos a NO tocar
| Archivo | Por qué |
|---------|---------|
| [ruta] | [razón] |

## Convenciones de Código
- Estilo: [snake_case, camelCase, etc.]
- Imports: [orden, estilo]

## Notas Adicionales
[Cualquier otra información relevante]
"""


def _write_template_file(path: str, kind: str):
    """Write a template file based on its kind."""
    templates = {
        "tareas": _TAREAS_PLANTILLA,
        "PLANTILLA.md": _PARAMETROS_PLANTILLA,
        "contexto.md": _PARAMETROS_CONTEXTO,
    }
    content = templates.get(kind, "")
    if content:
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)


def cmd_pull(args):
    """Download the configured model using Ollama."""
    config = get_config()
    model = config.get("executor.model", DEFAULT_MODEL)
    print(f"{Fore.CYAN}[INFO]{Fore.RESET} Pulling model: {Fore.YELLOW}{model}{Fore.RESET}...")
    try:
        subprocess.run(["ollama", "pull", model], check=True)
        print(f"{Fore.GREEN}[SUCCESS]{Fore.RESET} Model {model} is ready.")
    except Exception as e:
        print(f"{Fore.RED}[ERROR]{Fore.RESET} Failed to pull model: {e}")


def cmd_multi(args):
    """
    Run a task using the multi-agent orchestrator.

    Examples:
        cawl multi -c "Analiza src/, escribe tests y genera README"
        cawl multi -c "..." --workers coder,reviewer,documenter
        cawl multi -c "..." --parallel
    """
    from cawl.core.multi_agent import OrchestratorAgent, WorkerAgent

    project_path = os.path.abspath(args.project or os.getcwd())
    config = get_config(project_path=project_path)
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    activate_project_context(project_path, model=model)

    # Build workers from --workers flag (comma-separated role names)
    workers = None
    if args.workers:
        role_names = [r.strip() for r in args.workers.split(",") if r.strip()]
        workers = [
            WorkerAgent(role=role, project_path=project_path)
            for role in role_names
        ]
        print(
            f"{Fore.CYAN}[MULTI]{Fore.RESET} "
            f"Workers: {', '.join(w.role for w in workers)}"
        )

    orchestrator = OrchestratorAgent(
        model=model,
        workers=workers,
        project_path=project_path,
        parallel=args.parallel,
    )

    task = args.command
    if not task:
        print("Error: -c / --command es requerido para 'multi'.")
        sys.exit(1)

    print(BANNER)
    print(
        f"{Fore.CYAN}[MULTI]{Fore.RESET} Modo: "
        f"{'paralelo' if args.parallel else 'secuencial'}  "
        f"| Proyecto: {project_path}\n"
    )

    spinner = TerminalSpinner()
    spinner.start()
    try:
        result = orchestrator.run(task)
    finally:
        spinner.stop()

    print(f"\n{result}\n")


def cmd_watch(args):
    """
    Watch a task .md file and re-run it automatically on every save.

    Uses polling (os.path.getmtime) — no extra dependencies needed.
    Press Ctrl+C to stop.

    Race condition fix: uses a threading.Lock to prevent overlapping
    runs if the file changes while a previous run is still executing.
    """
    import time
    import threading

    if not args.task:
        print("Error: --task is required for 'watch' command.")
        sys.exit(1)

    task_path = os.path.abspath(args.task)
    if not os.path.exists(task_path):
        print(f"{Fore.RED}[ERROR]{Fore.RESET} Task file not found: {task_path}")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    config = get_config(project_path=project_path)
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    poll_interval = getattr(args, "interval", 2)
    activate_project_context(project_path, model=model)

    print(f"{Fore.CYAN}[WATCH]{Fore.RESET} Watching: {task_path}")
    print(f"{Fore.CYAN}[WATCH]{Fore.RESET} Poll interval: {poll_interval}s — press Ctrl+C to stop.\n")

    last_mtime: float = 0.0
    _run_lock = threading.Lock()
    _is_running = False

    try:
        while True:
            try:
                current_mtime = os.path.getmtime(task_path)
            except OSError:
                print(f"{Fore.RED}[WATCH ERROR]{Fore.RESET} Cannot stat {task_path}. Retrying...")
                time.sleep(poll_interval)
                continue

            if current_mtime != last_mtime:
                if last_mtime != 0.0:
                    # Skip if a run is still in progress
                    if not _run_lock.acquire(blocking=False):
                        if _is_running:
                            print(
                                f"\n{Fore.YELLOW}[WATCH]{Fore.RESET} "
                                f"Change detected but previous run still in progress — skipping."
                            )
                        last_mtime = current_mtime
                        time.sleep(poll_interval)
                        continue

                    try:
                        _is_running = True
                        print(
                            f"\n{Fore.YELLOW}[WATCH]{Fore.RESET} "
                            f"Change detected — re-running task..."
                        )
                        last_mtime = current_mtime
                        run_loop(
                            task_file=task_path,
                            project_path=project_path,
                        )
                        print(
                            f"\n{Fore.GREEN}[WATCH]{Fore.RESET} "
                            f"Run complete. Waiting for next change..."
                        )
                    except Exception as e:
                        print(f"{Fore.RED}[WATCH ERROR]{Fore.RESET} Run failed: {e}")
                    finally:
                        _is_running = False
                        _run_lock.release()

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n{Fore.CYAN}[WATCH]{Fore.RESET} Stopped.")


def cmd_status(args):
    """Check Ollama connection and model status."""
    project_path = os.getcwd()
    model = resolve_cli_model(
        getattr(args, "model", None),
        project_path=project_path,
        allow_selection=getattr(args, "select_model", False),
    )
    activate_project_context(project_path, model=model)
    agent = CawlAgent(model=model)
    print(agent.get_status())
    print_model_inventory(model)


def cmd_ui(args):
    """Launch the graphical UI."""
    try:
        from cawl.ui import launch_ui
    except ImportError as e:
        print(f"[ERROR] No se pudo cargar la UI: {e}")
        print("Asegúrate de tener PyQt5 instalado: pip install -e .")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    model = resolve_cli_model(
        args.model,
        project_path=project_path,
        allow_selection=getattr(args, "select_model", False),
    )
    activate_project_context(project_path, model=model)
    launch_ui(project_path=project_path, model=model)


def cmd_shell(args):
    """Launch the interactive shell alias."""
    project_path = os.path.abspath(args.project or os.getcwd())
    model = resolve_cli_model(
        args.model,
        project_path=project_path,
        allow_selection=getattr(args, "select_model", False),
    )
    activate_project_context(project_path, model=model)
    launch_interactive_shell(project_path=project_path, model=model)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        prog="cawl",
        description="CAWL - Local AI Agent (Ollama)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run a task or start the interactive shell")
    run_parser.add_argument("-c", "--query", type=str, default=None, dest="query",
                            help="Single query/command to run and exit")
    run_parser.add_argument("--task", type=str, default=None,
                            help="Path to task .md file (plan->execute loop)")
    run_parser.add_argument("--project", type=str, default=None,
                            help="Project directory (default: cwd)")
    run_parser.add_argument("--model", type=str, default=None,
                            help=f"Ollama model to use (default from config.yaml)")
    run_parser.add_argument("--select-model", action="store_true", default=False,
                            help="Mostrar los modelos locales de Ollama y elegir uno al iniciar")
    run_parser.add_argument("--execution-mode", type=str, default=None,
                            choices=["interactive", "trusted", "dry-run", "safe-only"],
                            help="Command execution mode (default: interactive)")
    run_parser.set_defaults(func=cmd_run)

    # plan
    plan_parser = subparsers.add_parser("plan", help="Show plan for a task without executing")
    plan_parser.add_argument("--task", required=True, help="Path to task .md file")
    plan_parser.add_argument("--project", type=str, default=None,
                             help="Project directory (default: cwd)")
    plan_parser.set_defaults(func=cmd_plan)

    # init
    init_parser = subparsers.add_parser("init", help="Initialize CAWL in a project")
    init_parser.add_argument("--project", type=str, default=None,
                             help="Project directory (default: cwd)")
    init_parser.set_defaults(func=cmd_init)

    # pull
    pull_parser = subparsers.add_parser("pull", help="Download the configured model")
    pull_parser.set_defaults(func=cmd_pull)

    # status
    status_parser = subparsers.add_parser("status", help="Check Ollama connection and model")
    status_parser.add_argument("--model", type=str, default=None,
                               help="Modelo a verificar (default from config.yaml)")
    status_parser.add_argument("--select-model", action="store_true", default=False,
                               help="Elegir un modelo local antes de consultar el estado")
    status_parser.set_defaults(func=cmd_status)

    # multi
    multi_parser = subparsers.add_parser("multi", help="Run a task with multi-agent orchestration")
    multi_parser.add_argument("-c", "--command", type=str, required=True,
                              help="Task to execute with multiple agents")
    multi_parser.add_argument("--workers", type=str, default=None,
                              help="Comma-separated worker roles (e.g. coder,reviewer,documenter)")
    multi_parser.add_argument("--project", type=str, default=None,
                              help="Project directory (default: cwd)")
    multi_parser.add_argument("--model", type=str, default=None,
                              help="Ollama model (default from config.yaml)")
    multi_parser.add_argument("--parallel", action="store_true", default=False,
                              help="Run independent subtasks in parallel threads")
    multi_parser.set_defaults(func=cmd_multi)

    # watch
    watch_parser = subparsers.add_parser("watch", help="Re-run task on every file save (Ctrl+C to stop)")
    watch_parser.add_argument("--task", required=True, help="Path to task .md file to watch")
    watch_parser.add_argument("--project", type=str, default=None,
                              help="Project directory (default: cwd)")
    watch_parser.add_argument("--model", type=str, default=None,
                              help="Ollama model to use (default from config.yaml)")
    watch_parser.add_argument("--interval", type=float, default=2.0,
                              help="Polling interval in seconds (default: 2)")
    watch_parser.set_defaults(func=cmd_watch)

    # ui
    ui_parser = subparsers.add_parser("ui", help="Launch graphical chat interface")
    ui_parser.add_argument("--project", type=str, default=None,
                           help="Project directory to open (default: cwd)")
    ui_parser.add_argument("--model", type=str, default=None,
                           help="Ollama model to use (default from config.yaml)")
    ui_parser.add_argument("--select-model", action="store_true", default=False,
                           help="Mostrar los modelos locales de Ollama y elegir uno al iniciar")
    ui_parser.set_defaults(func=cmd_ui)

    # shell
    shell_parser = subparsers.add_parser(
        "shell", help="Rich interactive shell with history, tab-completion, and context"
    )
    shell_parser.add_argument("--project", type=str, default=None,
                              help="Project directory (default: cwd)")
    shell_parser.add_argument("--model", type=str, default=None,
                              help="Ollama model to use (default from config.yaml)")
    shell_parser.add_argument("--select-model", action="store_true", default=False,
                              help="Mostrar los modelos locales de Ollama y elegir uno al iniciar")
    shell_parser.set_defaults(func=cmd_shell)

    args = parser.parse_args()

    if not args.command:
        # No subcommand -> default to the interactive shell
        project_path = os.getcwd()
        model = resolve_cli_model(None, project_path=project_path)
        activate_project_context(project_path, model=model)
        launch_interactive_shell(project_path=project_path, model=model)
        return

    args.func(args)


if __name__ == "__main__":
    main()
