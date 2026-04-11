"""Context manager for the CawlShell.

Tracks which files are currently in the LLM prompt context,
the active project directory, and the model in use.
"""

import os
from pathlib import Path
from typing import Optional


class ShellContext:
    """Manages the visible context for the shell session."""

    def __init__(
        self,
        project_path: str = ".",
        model: str = "qwen2.5-coder:7b",
    ):
        self.project_path = os.path.abspath(project_path)
        self.model = model
        self.context_files: list[str] = []  # files explicitly added to context
        self.auto_context: bool = True  # auto-add files mentioned in conversation

    # -- Project path --------------------------------------------------------

    def set_project(self, path: str) -> str:
        """Change the active project directory. Returns the new path."""
        self.project_path = os.path.abspath(path)
        return self.project_path

    # -- Context files -------------------------------------------------------

    def add_file(self, path: str) -> Optional[str]:
        """Add a file to the prompt context. Returns resolved path or None on error."""
        resolved = self._resolve_path(path)
        if resolved is None:
            return None
        if resolved not in self.context_files:
            self.context_files.append(resolved)
        return resolved

    def remove_file(self, path: str) -> bool:
        """Remove a file from context. Returns True if found and removed."""
        resolved = self._resolve_path(path)
        if resolved in self.context_files:
            self.context_files.remove(resolved)
            return True
        return False

    def clear_files(self) -> int:
        """Clear all context files. Returns count cleared."""
        count = len(self.context_files)
        self.context_files.clear()
        return count

    def get_context_prompt(self) -> str:
        """Build the context section for the system prompt."""
        if not self.context_files:
            return "No files in context."
        lines = ["Files in context:"]
        for f in self.context_files:
            lines.append(f"  - {f}")
        return "\n".join(lines)

    # -- Helpers -------------------------------------------------------------

    def _resolve_path(self, path: str) -> Optional[str]:
        """Resolve a path relative to project_path. Returns None if not found."""
        p = Path(path)
        if not p.is_absolute():
            p = Path(self.project_path) / p
        resolved = str(p)
        if not os.path.exists(resolved):
            return None
        return resolved

    def list_project_files(self, pattern: str = "**/*.py") -> list[str]:
        """List files in the project matching a glob pattern."""
        try:
            return [
                str(f.relative_to(self.project_path))
                for f in Path(self.project_path).glob(pattern)
                if f.is_file()
            ]
        except Exception:
            return []

    def format_status(self) -> str:
        """Return a one-line status summary."""
        ctx_count = len(self.context_files)
        ctx_info = f" | {ctx_count} file(s) in context" if ctx_count else ""
        return f"Project: {self.project_path} | Model: {self.model}{ctx_info}"
