"""Main execution loop for CAWL agent."""

from colorama import Fore, Style

from cawl.tasks.parser import parse_task_file
from cawl.core.planner import create_plan
from cawl.core.executor import execute_step
from cawl.core.status import status
from cawl.memory.project_memory import ProjectMemory


def run_loop(task_file: str = None, task_text: str = None, project_path: str = "."):
    """
    Read a task, plan, execute steps, and persist results to project-scoped memory.

    Each project_path has its own isolated .cawl/memory.json — no cross-project leakage.

    Args:
        task_file: Path to a .md task file (optional if task_text is given).
        task_text: Raw task text (optional if task_file is given).
        project_path: Root of the project to scope memory to.

    Returns:
        List of result dicts from each executed step.
    """
    # 1. Load task text
    if not task_text and task_file:
        task_text = parse_task_file(task_file)

    if not task_text:
        print(f"{Fore.RED}[ERROR]{Fore.RESET} No task text provided.")
        return []

    # 2. Load project-scoped memory
    memory = ProjectMemory(project_path)
    recent_runs = memory.get_recent_runs(limit=5)

    # 3. Generate plan
    status.emit("planning", "Generando plan...")
    print(f"{Fore.CYAN}[INFO]{Fore.RESET} Generating plan...")
    plan = create_plan(task_text, memory_context=recent_runs)
    print(f"{Fore.CYAN}[INFO]{Fore.RESET} Plan: {len(plan['steps'])} step(s).")

    # 4. Execute each step
    results = []
    for step in plan["steps"]:
        try:
            status.emit("step", f"Paso {step['id']}: {step['task'][:60]}")
            print(f"\n{Style.BRIGHT}{Fore.BLUE}--- Step {step['id']}: {step['task']} ---")
            result = execute_step(step, task_text=task_text, previous_results=results)
            results.append(result)

            action = result.get("action", "unknown")
            output = result.get("output", "")

            if action == "error":
                status.emit("error", str(output)[:80])
                print(f"{Fore.RED}[ERROR]{Fore.RESET} {output}")
            elif action == "skipped":
                print(f"{Fore.YELLOW}[SKIPPED]{Fore.RESET} {output}")
            else:
                status.emit("done", f"Paso {step['id']} completado")
                print(f"{Fore.GREEN}[SUCCESS]{Fore.RESET} {action}: {output}")

        except Exception as e:
            error_result = {"action": "error", "output": str(e)}
            results.append(error_result)
            print(f"{Fore.RED}[FATAL ERROR]{Fore.RESET} Step {step['id']}: {e}")
            break

    # 5. Persist run to this project's memory
    memory.append_run(task_text, results)

    return results
