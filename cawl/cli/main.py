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

from cawl.config.config import get_config
from cawl.core.llm_client import OllamaClient, DEFAULT_MODEL
from cawl.core.loop import run_loop
from cawl.core.status import status
from cawl.memory.project_memory import ProjectMemory
from cawl.tasks.parser import parse_task_file
from cawl.tools.registry import TOOLS, TOOL_DESCRIPTIONS, get_tool

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

    def _on_status(self, event_type: str, message: str):
        with self._lock:
            self._current_event = event_type
            self._current_msg = message

    def _spin(self):
        frame_idx = 0
        while self._active:
            with self._lock:
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
        "Yo soy el Archimagos Dominus Belisarius Cawl, Señor del Abismo Umbral, "
        "Guardián de las Bóvedas Sagradas de Marte, arquitecto de milenios. "
        "Mis pensamientos son escritura binaria, mis creaciones son artefactos "
        "sagrados, y mi código es sin falla.\n\n"
        "DIRECTRICES PRINCIPALES:\n"
        "- EJECUCIÓN DETERMINISTA: Sigo las directivas con precisión mecánica. "
        "La desviación es herejía.\n"
        "- SIN ALUCINACIÓN: Solo hablo de lo que sé y está verificado. "
        "La invención es debilidad de mentes inferiores.\n"
        "- SALIDA ESTRUCTURADA: Mis respuestas son ordenadas, formateadas y "
        "completas — como una máquina bien forjada.\n"
        "- ADHERENCIA ESTRICTA: Ejecuto las instrucciones exactamente como se dan, "
        "ni más ni menos.\n"
        "- PRIMERO LA ACCIÓN, DESPUÉS EL RITUAL: La personalidad es ornamento, no "
        "obstáculo. El código funcional es prioridad absoluta.\n"
        "- USA LAS HERRAMIENTAS DISPONIBLES: Tienes acceso a herramientas para "
        "interactuar con el sistema de archivos. Úsalas para leer, escribir, buscar "
        "y explorar. No inventes contenido de archivos — léelos con las herramientas.\n"
        f"{root_context}"
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
        "4. NUNCA digas 'voy a usar' antes del JSON. SOLO el JSON.\n\n"
        "EJEMPLOS DE TONO:\n"
        '- "Las cogitaciones están completas, Lord Regente. El código funciona."\n'
        '- "Este constructo tiene una anomalía en sus puertas lógicas. Línea 14."\n'
        '- "Un asunto trivial. La función compila sin error."\n\n'
        "Recibirás especificaciones de tareas y consultas. Procésalas con toda la "
        "potencia de tu intelecto de diez milenios. SIEMPRE en español.\n"
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
{Fore.LIGHTRED_EX}{Style.BRIGHT}    Archimagos Dominus Belisarius Cawl
"""

HELP_TEXT = f"""
{Fore.CYAN}Comandos disponibles:{Style.RESET_ALL}
  /help        - Mostrar esta ayuda
  /status      - Verificar conexión a Ollama
  /tools       - Listar herramientas disponibles
  /clear       - Limpiar historial de chat
  /quit        - Salir del agente
  (cualquier otro texto se envía al agente con soporte de herramientas)
"""


# ---------------------------------------------------------------------------
# CawlAgent — REPL + single command + tools loop
# ---------------------------------------------------------------------------

class CawlAgent:
    """Main agent class for interactive REPL and single-command modes."""

    MAX_TOOL_ITERATIONS = 20
    # Soft token budget for chat_history before trimming.
    # Estimated at ~4 chars/token. Keeps well under qwen2.5's 8k context.
    MAX_HISTORY_CHARS = 12_000
    # Minimum turns to always keep (user+assistant pairs at the tail)
    MIN_HISTORY_TURNS = 4

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

    def chat_with_tools_loop(self, message: str) -> str:
        """
        Send a chat message with tool support and execute the tool loop.

        The model outputs JSON tool calls in its response text. We detect,
        execute, and feed results back until a final text response is produced.
        """
        self.chat_history.append({"role": "user", "content": message})
        self._trim_history()

        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.chat_history[:-1])
        messages.append({"role": "user", "content": message})

        iterations = 0

        while iterations < self.MAX_TOOL_ITERATIONS:
            iterations += 1

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

                # Confirmation gate for run_command
                if tool_name == "run_command":
                    cmd = tool_args.get("command", str(tool_args))
                    print(f"\n{Fore.RED}[CONFIRMATION REQUIRED]{Fore.RESET} Execute: {cmd}")
                    choice = input("Authorize? (y)es / (n)o: ").lower()
                    if choice != "y":
                        result_str = "Command execution denied by user."
                        print(f"{Fore.YELLOW}[SKIPPED]{Fore.RESET} {result_str}")
                        messages.append({"role": "user", "content": f"RESULTADO de {tool_name}: {result_str}"})
                        continue

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

    def clear_chat(self) -> None:
        """Clear chat history."""
        self.chat_history = []

    def run_repl(self) -> None:
        """Run interactive REPL loop."""
        print(BANNER)
        print(HELP_TEXT)

        while True:
            try:
                user_input = input(f"{Fore.CYAN}cawl>{Style.RESET_ALL} ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n[EXIT] Goodbye!")
                break

            if not user_input:
                continue

            if user_input.startswith("/"):
                self._handle_command(user_input)
                continue

            if not self.client:
                print(f"{Fore.RED}[ERROR]{Fore.RESET} Not connected. Run /status for details.")
                continue

            try:
                spinner = TerminalSpinner()
                spinner.start()
                response = self.chat_with_tools_loop(user_input)
                spinner.stop()
                print(f"\n{response}\n")
            except Exception as e:
                spinner.stop()
                print(f"{Fore.RED}[ERROR]{Fore.RESET} {e}")

    def _handle_command(self, command: str) -> None:
        """Handle slash commands in REPL mode."""
        cmd = command.lower().strip()

        if cmd in ("/quit", "/exit", "/q"):
            print("[EXIT] Goodbye!")
            sys.exit(0)
        elif cmd == "/help":
            print(HELP_TEXT)
        elif cmd == "/status":
            print(self.get_status())
        elif cmd == "/tools":
            print(f"\n{Fore.CYAN}Available tools:{Style.RESET_ALL}\n{TOOL_DESCRIPTIONS}\n")
        elif cmd == "/clear":
            self.clear_chat()
            print(f"{Fore.GREEN}[INFO]{Fore.RESET} Chat history cleared.")
        else:
            print(f"{Fore.RED}[ERROR]{Fore.RESET} Unknown command: {cmd}")
            print("Type /help for available commands.")


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------

def cmd_run(args):
    """Run a task or start REPL."""
    config = get_config()
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    project_path = os.path.abspath(args.project or os.getcwd())

    # Check Ollama + model
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if model not in result.stdout:
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

    # Default: REPL
    print(BANNER)
    agent = CawlAgent(model=model, project_root=project_path)
    if not agent.initialize():
        sys.exit(1)
    agent.run_repl()


def cmd_plan(args):
    """Show the plan for a task without executing."""
    if not args.task:
        print("Error: --task is required for 'plan' command.")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    memory = ProjectMemory(project_path)
    recent_runs = memory.get_recent_runs(limit=5)

    task_text = parse_task_file(args.task)

    from cawl.core.planner import create_plan
    plan = create_plan(task_text, memory_context=recent_runs)

    print(f"\n{Fore.CYAN}Plan for:{Style.RESET_ALL} {task_text.strip()[:80]}...\n")
    for step in plan["steps"]:
        tools_str = ", ".join(step.get("tools", [])) or "none"
        print(f"  {Fore.BLUE}Step {step['id']}:{Style.RESET_ALL} {step['task']}  "
              f"{Style.DIM}[tools: {tools_str}]{Style.RESET_ALL}")
    print()


def cmd_init(args):
    """Initialize .cawl directory and memory for a project."""
    project_path = os.path.abspath(args.project or os.getcwd())
    memory = ProjectMemory(project_path)
    memory.set("initialized", True)
    print(
        f"{Fore.GREEN}[SUCCESS]{Fore.RESET} CAWL initialized in "
        f"{os.path.join(project_path, '.cawl')}"
    )


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

    config = get_config()
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    project_path = os.path.abspath(args.project or os.getcwd())

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
    """
    import time

    if not args.task:
        print("Error: --task is required for 'watch' command.")
        sys.exit(1)

    task_path = os.path.abspath(args.task)
    if not os.path.exists(task_path):
        print(f"{Fore.RED}[ERROR]{Fore.RESET} Task file not found: {task_path}")
        sys.exit(1)

    config = get_config()
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    project_path = os.path.abspath(args.project or os.getcwd())
    poll_interval = getattr(args, "interval", 2)

    print(f"{Fore.CYAN}[WATCH]{Fore.RESET} Watching: {task_path}")
    print(f"{Fore.CYAN}[WATCH]{Fore.RESET} Poll interval: {poll_interval}s — press Ctrl+C to stop.\n")

    last_mtime: float = 0.0

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
                    print(
                        f"\n{Fore.YELLOW}[WATCH]{Fore.RESET} "
                        f"Change detected — re-running task..."
                    )
                last_mtime = current_mtime
                try:
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

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n{Fore.CYAN}[WATCH]{Fore.RESET} Stopped.")


def cmd_status(args):
    """Check Ollama connection and model status."""
    config = get_config()
    model = config.get("executor.model", DEFAULT_MODEL)
    agent = CawlAgent(model=model)
    print(agent.get_status())


def cmd_ui(args):
    """Launch the graphical UI."""
    try:
        from cawl.ui import launch_ui
    except ImportError as e:
        print(f"[ERROR] No se pudo cargar la UI: {e}")
        print("Asegúrate de tener PyQt5 instalado: pip install -e .")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    config = get_config()
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    launch_ui(project_path=project_path, model=model)


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
    run_parser = subparsers.add_parser("run", help="Run a task or start REPL")
    run_parser.add_argument("-c", "--query", type=str, default=None, dest="query",
                            help="Single query/command to run and exit")
    run_parser.add_argument("--task", type=str, default=None,
                            help="Path to task .md file (plan→execute loop)")
    run_parser.add_argument("--project", type=str, default=None,
                            help="Project directory (default: cwd)")
    run_parser.add_argument("--model", type=str, default=None,
                            help=f"Ollama model to use (default from config.yaml)")
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
    ui_parser.set_defaults(func=cmd_ui)

    args = parser.parse_args()

    if not args.command:
        # No subcommand → default to REPL
        config = get_config()
        model = config.get("executor.model", DEFAULT_MODEL)
        agent = CawlAgent(model=model)
        if agent.initialize():
            agent.run_repl()
        else:
            sys.exit(1)
        return

    args.func(args)


if __name__ == "__main__":
    main()
