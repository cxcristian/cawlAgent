"""CawlShell — Interactive shell inspired by Qwen Code terminal.

Features:
  - Navigable history (Up/Down)
  - Tab-completion for commands, files, and tool names
  - Visible context (project directory, model, files in prompt)
  - Verbose mode (tool calls, reasoning steps, timing)
  - Multi-line input (Shift+Enter for newline)
"""

from cawl.shell.shell import CawlShell

__all__ = ["CawlShell"]
