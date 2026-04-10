"""Global memory management for cross-project data."""

import json
import os


class GlobalMemory:
    """Memory storage shared across all projects (~/.cawl/global_memory.json)."""

    def __init__(self):
        self.home_dir = os.path.expanduser("~")
        self.cawl_dir = os.path.join(self.home_dir, ".cawl")
        self.memory_file = os.path.join(self.cawl_dir, "global_memory.json")
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
        return self._data.get(key)

    def set(self, key: str, value):
        self._data[key] = value
        self._save()


# Singleton
_global_memory = None


def get_global_memory() -> GlobalMemory:
    global _global_memory
    if _global_memory is None:
        _global_memory = GlobalMemory()
    return _global_memory
