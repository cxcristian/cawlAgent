"""Project memory management using .cawl/memory.json.

Each project maintains its own isolated memory in {project_path}/.cawl/memory.json.
No cross-project data leaks from this module.
"""

import json
import os


class ProjectMemory:
    """Memory storage scoped to a single project directory."""

    def __init__(self, project_path: str = "."):
        self.project_path = os.path.abspath(project_path)
        self.cawl_dir = os.path.join(self.project_path, ".cawl")
        self.memory_file = os.path.join(self.cawl_dir, "memory.json")
        os.makedirs(self.cawl_dir, exist_ok=True)
        self._data = self._load()

    def _load(self) -> dict:
        if os.path.exists(self.memory_file):
            with open(self.memory_file, "r", encoding="utf-8") as f:
                try:
                    return json.load(f)
                except json.JSONDecodeError:
                    return {}
        return {}

    def _save(self):
        with open(self.memory_file, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, key: str):
        """Get a value from this project's memory."""
        return self._data.get(key)

    def set(self, key: str, value):
        """Set a value in this project's memory and persist to disk."""
        self._data[key] = value
        self._save()

    def get_recent_runs(self, limit: int = 5) -> list:
        """Return the last N task run summaries for context injection."""
        runs = self._data.get("runs", [])
        return runs[-limit:]

    def append_run(self, task: str, results: list):
        """Append a completed run summary to memory."""
        runs = self._data.get("runs", [])
        runs.append({
            "task": task[:200],
            "steps": [
                {
                    "action": r.get("action"),
                    "tool": r.get("tool"),
                    "output": str(r.get("output", ""))[:300],
                }
                for r in results
            ],
        })
        # Keep only last 20 runs to avoid bloat
        self._data["runs"] = runs[-20:]
        self._save()
