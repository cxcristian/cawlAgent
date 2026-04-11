"""Configuration loader for CAWL agent.

Supports a layered override system (highest priority wins):
  1. Environment variables (CAWL_EXECUTOR_MODEL, CAWL_PLANNER_MODEL, etc.)
  2. Per-project config ({project_path}/.cawl/config.yaml)
  3. User-level config (~/.cawl/config.yaml)
  4. Bundled default config (cawl/config/config.yaml)

Env vars use double underscore for nested keys, e.g.:
    CAWL_EXECUTOR_MODEL=qwen2.5:14b  →  executor.model
"""

import yaml
import os


class Config:
    def __init__(self, config_path=None, project_path=None):
        self.config_path = config_path
        self.project_path = project_path or os.getcwd()
        self.data = self._load_config()

    def _load_config(self):
        """Load config with layered overrides (lowest → highest priority)."""
        data = {}

        # Layer 1: bundled default
        if self.config_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.config_path = os.path.join(base_dir, "config.yaml")
        data.update(self._load_yaml(self.config_path))

        # Layer 2: user-level (~/.cawl/config.yaml)
        user_config = os.path.expanduser("~/.cawl/config.yaml")
        data.update(self._load_yaml(user_config))

        # Layer 3: per-project ({project_path}/.cawl/config.yaml)
        project_config = os.path.join(self.project_path, ".cawl", "config.yaml")
        data.update(self._load_yaml(project_config))

        # Layer 4: environment variables
        data.update(self._load_env_vars())

        return data

    @staticmethod
    def _load_yaml(path):
        """Safely load a YAML file, returning {} on missing or invalid."""
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r") as f:
                result = yaml.safe_load(f)
                return result if isinstance(result, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _load_env_vars():
        """
        Parse CAWL_* environment variables into a nested dict.

        CAWL_EXECUTOR_MODEL → {"executor": {"model": ...}}
        CAWL_PATHS_MEMORY   → {"paths": {"memory": ...}}
        """
        result = {}
        prefix = "CAWL_"
        for key, value in os.environ.items():
            if key.upper().startswith(prefix):
                parts = key[len(prefix):].lower().split("__")
                # Build nested dict
                d = result
                for part in parts[:-1]:
                    d = d.setdefault(part, {})
                d[parts[-1]] = value
        return result

    def get(self, key, default=None):
        keys = key.split(".")
        val = self.data
        for k in keys:
            if isinstance(val, dict):
                val = val.get(k)
            else:
                return default
        return val if val is not None else default

    def set(self, key, value):
        """Set a config value in memory (does NOT persist to disk)."""
        keys = key.split(".")
        d = self.data
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value


# Singleton
_config = None


def get_config(project_path=None):
    global _config
    if _config is None:
        _config = Config(project_path=project_path)
    return _config


def reload_config(project_path=None):
    """Force reload the configuration (useful after project changes)."""
    global _config
    _config = Config(project_path=project_path)
    return _config
