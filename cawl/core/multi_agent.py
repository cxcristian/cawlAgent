"""
CAWL Multi-Agent System — Orchestrator + Worker agents.

Arquitectura:
    OrchestratorAgent
        ├── descompone la tarea en sub-tareas
        ├── lanza WorkerAgent(s) en paralelo o secuencial
        └── consolida resultados en respuesta final

Uso básico:
    from cawl.core.multi_agent import OrchestratorAgent

    orchestrator = OrchestratorAgent(model="qwen2.5-coder:7b")
    result = orchestrator.run("Analiza src/, escribe tests y genera el README")
    print(result)

Uso con roles personalizados:
    from cawl.core.multi_agent import WorkerAgent, OrchestratorAgent

    workers = [
        WorkerAgent(role="coder",      instructions="Solo escribe código Python."),
        WorkerAgent(role="reviewer",   instructions="Revisa código y reporta problemas."),
        WorkerAgent(role="documenter", instructions="Solo escribe documentación Markdown."),
    ]
    orchestrator = OrchestratorAgent(workers=workers)
    orchestrator.run("Refactoriza el módulo auth y documéntalo")
"""

from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

from cawl.core.llm_client import get_llm_client, OllamaClient, DEFAULT_MODEL
from cawl.core.status import status
from cawl.tools.registry import TOOL_DESCRIPTIONS, get_tool, TOOLS


# ---------------------------------------------------------------------------
# WorkerAgent
# ---------------------------------------------------------------------------

class WorkerAgent:
    """
    Un agente especializado con su propio historial, tools y rol.

    Args:
        role:         Nombre del rol (ej: "coder", "reviewer", "documenter").
        instructions: Instrucciones adicionales para el system prompt.
        model:        Modelo Ollama a usar (hereda del orquestador si None).
        tools:        Lista de nombres de tools disponibles (None = todas).
        project_path: Ruta del proyecto (para contexto en prompts).
        parallel_tools: Si True, ejecuta tool calls independientes en paralelo.
    """

    MAX_TOOL_ITERATIONS = 15
    MAX_PARALLEL_TOOLS = 4  # Max concurrent tool calls

    def __init__(
        self,
        role: str = "worker",
        instructions: str = "",
        model: Optional[str] = None,
        tools: Optional[list[str]] = None,
        project_path: str = ".",
        parallel_tools: bool = True,
    ):
        self.role = role
        self.instructions = instructions
        self.model = model  # resolved at run time if None
        self.allowed_tools = tools  # None = all tools
        self.project_path = project_path
        self.chat_history: list[dict] = []
        self._client: Optional[OllamaClient] = None
        self.parallel_tools = parallel_tools

    def _get_client(self, fallback_model: str) -> OllamaClient:
        model = self.model or fallback_model
        if self._client is None or self._client.model != model:
            self._client = OllamaClient(model=model)
        return self._client

    def _build_system_prompt(self) -> str:
        tool_filter = ""
        if self.allowed_tools:
            lines = []
            for name in self.allowed_tools:
                func = get_tool(name)
                if func:
                    # Extract just the relevant line from TOOL_DESCRIPTIONS
                    for line in TOOL_DESCRIPTIONS.splitlines():
                        if line.strip().startswith(f"- {name}("):
                            lines.append(line)
                            break
            tool_filter = "\n".join(lines)
        else:
            tool_filter = TOOL_DESCRIPTIONS

        return (
            f"Eres el agente '{self.role}' del sistema CAWL multi-agente.\n"
            f"Proyecto activo: {self.project_path}\n\n"
            f"INSTRUCCIONES DE ROL:\n{self.instructions or 'Ejecuta la tarea asignada con precisión.'}\n\n"
            "REGLAS:\n"
            "- Responde SIEMPRE en español.\n"
            "- Sin disclaimers. Código completo y ejecutable.\n"
            "- Usa herramientas cuando sea necesario.\n"
            "- Reporta resultados concretos al finalizar.\n\n"
            "HERRAMIENTAS DISPONIBLES:\n"
            "Para usar una herramienta, responde ÚNICAMENTE con JSON:\n"
            "```json\n"
            '{"name": "tool_name", "arguments": {"arg": "value"}}\n'
            "```\n\n"
            f"{tool_filter}\n"
        )

    def _execute_single_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a single tool call and return result string."""
        if self.allowed_tools and tool_name not in self.allowed_tools:
            result_str = (
                f"[ERROR] Tool '{tool_name}' not in allowed list for role '{self.role}'. "
                f"Allowed: {self.allowed_tools}"
            )
            status.emit("error", result_str[:80])
            return result_str

        func = get_tool(tool_name)
        if func is None:
            result_str = f"[ERROR] Unknown tool: {tool_name}"
            status.emit("error", result_str)
            return result_str

        status.emit("tool_call", f"[{self.role}] {tool_name}({str(tool_args)[:50]})")
        try:
            result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
            result_str = str(result)
            status.emit("tool_result", f"[{self.role}] {tool_name} → {result_str[:60]}")
            return result_str
        except Exception as e:
            result_str = f"[ERROR] Tool raised: {e}"
            status.emit("error", result_str[:80])
            return result_str

    def _execute_tool_calls(self, tool_calls: list[dict]) -> list[tuple[str, str]]:
        """
        Execute multiple tool calls, potentially in parallel.
        Returns list of (tool_name, result) tuples.
        """
        if not self.parallel_tools or len(tool_calls) <= 1:
            # Sequential execution
            results = []
            for tool_call in tool_calls:
                tool_name = tool_call.get("name", "")
                tool_args = tool_call.get("arguments", {})
                result_str = self._execute_single_tool(tool_name, tool_args)
                results.append((tool_name, result_str))
            return results

        # Parallel execution with thread pool
        results = [None] * len(tool_calls)
        
        def execute_and_store(idx, tc):
            tool_name = tc.get("name", "")
            tool_args = tc.get("arguments", {})
            result = self._execute_single_tool(tool_name, tool_args)
            results[idx] = (tool_name, result)

        with ThreadPoolExecutor(max_workers=min(len(tool_calls), self.MAX_PARALLEL_TOOLS)) as executor:
            futures = [
                executor.submit(execute_and_store, i, tc)
                for i, tc in enumerate(tool_calls)
            ]
            for future in as_completed(futures):
                future.result()  # Wait and propagate exceptions

        return results

    def run(self, task: str, fallback_model: str = DEFAULT_MODEL) -> str:
        """
        Execute a task and return the result as a string.

        Args:
            task:           The sub-task description.
            fallback_model: Model to use if self.model is None.

        Returns:
            The agent's final text response.
        """
        client = self._get_client(fallback_model)
        system_prompt = self._build_system_prompt()

        status.emit("agent", f"[{self.role}] Iniciando: {task[:50]}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

        for iteration in range(self.MAX_TOOL_ITERATIONS):
            status.emit("thinking", f"[{self.role}] Iteración {iteration + 1}...")

            response = client.chat_with_tools(messages=messages, temperature=0.1)
            content = response.get("content", "")
            tool_calls = response.get("tool_calls", [])

            if not tool_calls:
                status.emit("done", f"[{self.role}] Tarea completada")
                return content

            # Execute tool calls (potentially in parallel)
            results = self._execute_tool_calls(tool_calls)

            # Append all results to messages
            for tool_name, result_str in results:
                # Truncate very long results to avoid bloating message history
                max_result_len = 1000  # Limit tool result in history
                truncated_result = result_str[:max_result_len]
                if len(result_str) > max_result_len:
                    truncated_result += f"\n... [TRUNCATED: {len(result_str) - max_result_len} chars]"
                
                messages.append({
                    "role": "user",
                    "content": f"RESULTADO de {tool_name}: {truncated_result}",
                })

        return f"[{self.role}] Máximo de iteraciones alcanzado ({self.MAX_TOOL_ITERATIONS})."


# ---------------------------------------------------------------------------
# OrchestratorAgent
# ---------------------------------------------------------------------------

class OrchestratorAgent:
    """
    Orquestador que descompone una tarea en sub-tareas y las delega a WorkerAgents.

    Por defecto usa un único WorkerAgent genérico. Si pasas una lista de workers,
    el orquestador los asigna inteligentemente según el tipo de sub-tarea.

    Args:
        model:        Modelo Ollama para el orquestador y workers por defecto.
        workers:      Lista de WorkerAgent pre-configurados (opcional).
        project_path: Raíz del proyecto.
        parallel:     Si True, ejecuta workers en paralelo con threads (default: False).
    """

    MAX_JSON_RETRIES = 2

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        workers: Optional[list[WorkerAgent]] = None,
        project_path: str = ".",
        parallel: bool = False,
    ):
        self.model = model
        self.project_path = project_path
        self.parallel = parallel
        self._client: Optional[OllamaClient] = None

        # Default: one generic worker
        self.workers: list[WorkerAgent] = workers or [
            WorkerAgent(role="worker", project_path=project_path)
        ]
        # Ensure all workers have the same project path if not set
        for w in self.workers:
            if w.project_path == ".":
                w.project_path = project_path

    def _get_client(self) -> OllamaClient:
        if self._client is None:
            self._client = OllamaClient(model=self.model)
        return self._client

    @staticmethod
    def _extract_json(text: str) -> str:
        fence = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
        if fence:
            return fence.group(1).strip()
        brace = re.search(r"\{[\s\S]*\}", text)
        if brace:
            return brace.group(0)
        return text.strip()

    def _decompose(self, task: str) -> list[dict]:
        """
        Ask the LLM to break the task into sub-tasks, each assigned to a worker role.

        Returns:
            List of dicts: [{id, subtask, role, depends_on}]
        """
        roles_desc = "\n".join(
            f"  - '{w.role}': {w.instructions[:100] or 'agente genérico'}"
            for w in self.workers
        )

        system_prompt = (
            "Eres el orquestador del sistema CAWL multi-agente.\n"
            "Descompón la tarea en sub-tareas asignables a agentes especializados.\n\n"
            f"Agentes disponibles:\n{roles_desc}\n\n"
            "Devuelve ÚNICAMENTE JSON válido con esta estructura:\n"
            '{"subtasks": [{"id": 1, "subtask": "descripción", "role": "nombre_del_rol", "depends_on": []}]}\n'
            "- 'depends_on' es una lista de IDs de sub-tareas que deben completarse antes.\n"
            "- Usa el rol más apropiado para cada sub-tarea.\n"
            "- Sin texto adicional. Solo JSON."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Tarea principal: {task}"},
        ]

        client = self._get_client()
        last_error = None

        for attempt in range(1 + self.MAX_JSON_RETRIES):
            try:
                status.emit("planning", f"Descomponiendo tarea (intento {attempt + 1})...")
                response_text = client.chat(messages=messages, json_format=True)
                clean = self._extract_json(response_text)
                data = json.loads(clean)
                subtasks = data.get("subtasks", [])
                if not subtasks:
                    raise ValueError("Empty subtasks list")
                status.emit("planning", f"Descomposición: {len(subtasks)} sub-tarea(s)")
                return subtasks
            except Exception as e:
                last_error = e
                if attempt < self.MAX_JSON_RETRIES:
                    status.emit("retry", f"JSON inválido, reintentando descomposición...")
                    messages.append({
                        "role": "user",
                        "content": f"Error de parseo: {e}. Devuelve SOLO JSON válido.",
                    })

        # Fallback: single subtask for the first worker
        status.emit("error", f"Descomposición fallida: {last_error}. Usando plan simple.")
        return [{"id": 1, "subtask": task, "role": self.workers[0].role, "depends_on": []}]

    def _get_worker_by_role(self, role: str) -> WorkerAgent:
        """Find a worker by role name, fallback to first worker."""
        for w in self.workers:
            if w.role == role:
                return w
        return self.workers[0]

    def _consolidate(self, task: str, results: dict[int, str]) -> str:
        """
        Ask the LLM to synthesize all worker results into a final response.
        """
        results_text = "\n\n".join(
            f"[Sub-tarea {sid}]\n{res}" for sid, res in sorted(results.items())
        )
        messages = [
            {
                "role": "system",
                "content": (
                    "Eres el orquestador CAWL. Consolida los resultados de los agentes "
                    "en una respuesta cohesiva y completa para el usuario.\n"
                    "Responde en español. Sin disclaimers. Sé directo y técnico."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Tarea original: {task}\n\n"
                    f"Resultados de los agentes:\n{results_text}\n\n"
                    "Proporciona el resumen final consolidado."
                ),
            },
        ]
        status.emit("thinking", "Consolidando resultados...")
        client = self._get_client()
        try:
            return client.chat(messages=messages)
        except Exception as e:
            return f"[Consolidación falló: {e}]\n\nResultados raw:\n{results_text}"

    def run(self, task: str) -> str:
        """
        Run the multi-agent pipeline for the given task.

        1. Decompose task into subtasks
        2. Execute subtasks (parallel or sequential, respecting depends_on)
        3. Consolidate and return final result

        Returns:
            Final consolidated response string.
        """
        status.emit("agent", f"Orquestador iniciado: {task[:60]}")

        subtasks = self._decompose(task)
        results: dict[int, str] = {}
        completed: set[int] = set()

        if self.parallel:
            return self._run_parallel(task, subtasks, results, completed)
        else:
            return self._run_sequential(task, subtasks, results, completed)

    def _run_sequential(
        self,
        task: str,
        subtasks: list[dict],
        results: dict[int, str],
        completed: set[int],
    ) -> str:
        """Execute subtasks one by one, respecting depends_on order."""
        # Sort by dependency (simple topological pass)
        pending = list(subtasks)
        max_passes = len(pending) * 2

        for _ in range(max_passes):
            if not pending:
                break
            for st in list(pending):
                sid = st["id"]
                deps = st.get("depends_on", [])
                if all(d in completed for d in deps):
                    worker = self._get_worker_by_role(st.get("role", "worker"))
                    status.emit("step", f"Sub-tarea {sid} → [{worker.role}]: {st['subtask'][:50]}")

                    # Include context from dependencies
                    context = ""
                    if deps:
                        context = "\n\nContexto de pasos anteriores:\n" + "\n".join(
                            f"[{d}]: {results[d][:300]}" for d in deps if d in results
                        )

                    result = worker.run(st["subtask"] + context, fallback_model=self.model)
                    results[sid] = result
                    completed.add(sid)
                    pending.remove(st)
                    break  # restart loop after each completion

        if len(results) == 1:
            return list(results.values())[0]

        return self._consolidate(task, results)

    def _run_parallel(
        self,
        task: str,
        subtasks: list[dict],
        results: dict[int, str],
        completed: set[int],
    ) -> str:
        """
        Execute independent subtasks in parallel threads.
        Tasks with depends_on are executed after their dependencies complete.
        """
        results_lock = threading.Lock()
        completed_lock = threading.Lock()

        def run_worker(st: dict):
            worker = self._get_worker_by_role(st.get("role", "worker"))
            sid = st["id"]
            status.emit("step", f"[PARALLEL] Sub-tarea {sid} → [{worker.role}]")

            context = ""
            deps = st.get("depends_on", [])
            if deps:
                with results_lock:
                    context = "\n\nContexto:\n" + "\n".join(
                        f"[{d}]: {results.get(d, '')[:300]}" for d in deps
                    )

            result = worker.run(st["subtask"] + context, fallback_model=self.model)
            with results_lock:
                results[sid] = result
            with completed_lock:
                completed.add(sid)

        # Group subtasks by dependency wave
        remaining = list(subtasks)
        max_waves = len(remaining) + 1

        for _ in range(max_waves):
            if not remaining:
                break
            # Find all tasks whose dependencies are satisfied
            ready = [
                st for st in remaining
                if all(d in completed for d in st.get("depends_on", []))
            ]
            if not ready:
                break  # circular dependency or unresolvable

            threads = [threading.Thread(target=run_worker, args=(st,)) for st in ready]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            for st in ready:
                remaining.remove(st)

        if len(results) == 1:
            return list(results.values())[0]

        return self._consolidate(task, results)
