"""Tab-completion provider for CawlShell using prompt_toolkit.

Completes:
  - Slash commands (/help, /status, /tools, etc.)
  - File paths from the project directory
  - Tool names (read_file, write_file, etc.) when typing a tool call
"""

from prompt_toolkit.completion import Completer, Completion
from pathlib import Path
import os


SLASH_COMMANDS = [
    "/help", "/status", "/session", "/models", "/tools", "/clear", "/reset",
    "/verbose", "/compact", "/context", "/add", "/remove", "/clear-context",
    "/project", "/model", "/quit", "/exit",
]

# Reverse lookup: prefix -> full command
_COMMAND_MAP = {cmd: cmd for cmd in SLASH_COMMANDS}


class CawlCompleter(Completer):
    """Completer for the CawlShell input prompt."""

    def __init__(
        self,
        context,
        tool_names: list[str],
    ):
        self.context = context
        self.tool_names = tool_names

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        word = document.get_word_before_cursor()

        if not word:
            return

        # Slash commands
        if text.startswith("/"):
            yield from self._complete_command(word)
            return

        # If typing inside quotes (likely a file path in a tool argument)
        if '"' in text or "'" in text:
            yield from self._complete_file(word)
            return

        # Tool names when typing a tool call
        yield from self._complete_tool(word)

        # Fallback: file paths
        yield from self._complete_file(word)

    def _complete_command(self, word: str):
        for cmd in sorted(SLASH_COMMANDS):
            if cmd.startswith(word):
                yield Completion(cmd, start_position=-len(word))

    def _complete_file(self, word: str):
        """Complete file paths relative to project directory."""
        try:
            # Strip quotes
            clean = word.strip('"').strip("'")
            p = Path(self.context.project_path)

            # Determine the directory to search
            if "/" in clean or "\\" in clean:
                # User typed a partial path
                dir_part = clean.rsplit("/", 1)[0] if "/" in clean else clean.rsplit("\\", 1)[0]
                search_dir = p / dir_part
                prefix = clean.rsplit("/", 1)[-1] if "/" in clean else clean.rsplit("\\", 1)[-1]
            else:
                search_dir = p
                prefix = clean

            if not search_dir.exists():
                return

            for entry in search_dir.iterdir():
                name = entry.name
                if name.startswith(prefix) and not name.startswith(".."):
                    suffix = "/" if entry.is_dir() else ""
                    completion = f"{entry.relative_to(p)}{suffix}"
                    # Re-add the directory prefix the user already typed
                    full = completion
                    yield Completion(full, start_position=-len(clean))

        except Exception:
            pass

    def _complete_tool(self, word: str):
        for name in self.tool_names:
            if name.startswith(word.lower()):
                yield Completion(name, start_position=-len(word))
