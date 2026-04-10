"""
CAWL CLI - Command-line interface for the Cawl agent.

Modes:
  cawl run                    # Interactive REPL (default)
  cawl run --task file.md     # Run task file through plan→execute loop
  cawl run -c "query"         # Single command with tools
  cawl plan --task file.md    # Show plan without executing
  cawl init [--project PATH]  # Initialize .cawl in a project
  cawl pull                   # Download configured model via Ollama
  cawl status                 # Check Ollama connection and model
"""

import argparse
import json
import os
import subprocess
import sys
from typing import Optional

from colorama import init, Fore, Style

from cawl.config.config import get_config
from cawl.core.llm_client import OllamaClient, DEFAULT_MODEL
from cawl.core.loop import run_loop
from cawl.memory.project_memory import ProjectMemory
from cawl.tasks.parser import parse_task_file
from cawl.tools.registry import TOOLS, TOOL_DESCRIPTIONS, get_tool

init(autoreset=True)

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
{Fore.CYAN}{Style.BRIGHT}    ██████╗ █████╗ ██╗    ██╗██╗     
{Fore.CYAN}{Style.BRIGHT}   ██╔════╝██╔══██╗██║    ██║██║     
{Fore.MAGENTA}{Style.BRIGHT}   ██║     ███████║██║ █╗ ██║██║     
{Fore.MAGENTA}{Style.BRIGHT}   ██║     ██╔══██║██║███╗██║██║     
{Fore.CYAN}{Style.BRIGHT}   ╚██████╗██║  ██║╚███╔███╔╝███████╗
{Fore.CYAN}{Style.BRIGHT}    ╚═════╝╚═╝  ╚═╝ ╚══╝╚══╝ ╚══════╝
{Style.RESET_ALL}
{Fore.WHITE}{Style.DIM}    Control & Action Web Loop | v0.2.0
    Archimagos Dominus Belisarius Cawl
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

    def chat_with_tools_loop(self, message: str) -> str:
        """
        Send a chat message with tool support and execute the tool loop.

        The model outputs JSON tool calls in its response text. We detect,
        execute, and feed results back until a final text response is produced.
        """
        self.chat_history.append({"role": "user", "content": message})

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
                response = self.chat_with_tools_loop(user_input)
                print(f"\n{response}\n")
            except Exception as e:
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

    # Single command mode
    if args.command:
        agent = CawlAgent(model=model, project_root=project_path)
        if not agent.initialize():
            sys.exit(1)
        result = agent.chat_with_tools_loop(args.command)
        print(result)
        return

    # Task file mode (plan → execute loop)
    if args.task:
        print(BANNER)
        print(f"{Fore.YELLOW}[PLANNING]{Fore.RESET} Project: {project_path}")
        run_loop(task_file=args.task, project_path=project_path)
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
              f"{Fore.DIM}[tools: {tools_str}]{Style.RESET_ALL}")
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


def cmd_status(args):
    """Check Ollama connection and model status."""
    config = get_config()
    model = config.get("executor.model", DEFAULT_MODEL)
    agent = CawlAgent(model=model)
    print(agent.get_status())


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
    run_parser.add_argument("-c", "--command", type=str, default=None,
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


def cmd_ui(args):
    """Launch the graphical UI."""
    try:
        from cawl.ui import launch_ui
    except ImportError as e:
        print(f"[ERROR] No se pudo cargar la UI: {e}")
        print("Asegúrate de tener PyQt5 instalado: pip install PyQt5")
        sys.exit(1)

    project_path = os.path.abspath(args.project or os.getcwd())
    config = get_config()
    model = args.model or config.get("executor.model", DEFAULT_MODEL)
    launch_ui(project_path=project_path, model=model)
