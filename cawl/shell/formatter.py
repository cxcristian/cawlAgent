"""Output formatter for CawlShell.

Handles:
  - Verbose vs quiet mode output
  - Tool call display
  - Streaming token display
  - Error formatting
"""

import time
from typing import Optional


class OutputFormatter:
    """Formats shell output for terminal display."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self._token_count = 0
        self._start_time: Optional[float] = None

    # -- Lifecycle -----------------------------------------------------------

    def start_timer(self):
        """Mark the start of a request."""
        self._start_time = time.monotonic()
        self._token_count = 0

    def elapsed(self) -> str:
        """Return formatted elapsed time."""
        if self._start_time is None:
            return "?s"
        elapsed = time.monotonic() - self._start_time
        if elapsed < 1:
            return f"{elapsed * 1000:.0f}ms"
        return f"{elapsed:.1f}s"

    # -- Tool calls ----------------------------------------------------------

    def format_tool_call(self, tool_name: str, args: dict) -> str:
        """Format a tool call for display."""
        import json
        args_str = json.dumps(args, indent=2, ensure_ascii=False)
        if self.verbose:
            return f"  ▸ TOOL: {tool_name}\n    Args: {args_str}"
        return f"  ▸ {tool_name}(...)"

    def format_tool_result(self, tool_name: str, output: str) -> str:
        """Format a tool result for display."""
        preview = output[:200].replace("\n", " ")
        suffix = "..." if len(output) > 200 else ""
        if self.verbose:
            lines = output.split("\n")
            display = "\n".join(f"    {l}" for l in lines[:20])
            truncated = f"\n    ... ({len(lines) - 20} more lines)" if len(lines) > 20 else ""
            return f"  ✓ {tool_name} →\n{display}{truncated}"
        return f"  ✓ {tool_name} → {preview}{suffix}"

    # -- Streaming -----------------------------------------------------------

    def stream_token(self, token: str):
        """Process a streaming token. Returns display string or empty."""
        self._token_count += 1
        return token

    # -- Final response ------------------------------------------------------

    def format_response(self, text: str) -> str:
        """Format the final LLM response."""
        if not text:
            return ""
        return text

    # -- Errors --------------------------------------------------------------

    def format_error(self, message: str) -> str:
        """Format an error message."""
        return f"  ✘ Error: {message}"

    # -- Status --------------------------------------------------------------

    def format_status_change(self, event_type: str, message: str) -> str:
        """Format a status event for verbose display."""
        icons = {
            "thinking": "○",
            "planning": "▦",
            "tool_call": "▸",
            "tool_result": "✓",
            "step": "●",
            "retry": "↺",
            "trim": "✂",
            "done": "✔",
            "error": "✘",
            "agent": "◆",
        }
        icon = icons.get(event_type, "○")
        if self.verbose:
            return f"  [{icon}] {event_type}: {message[:80]}"
        return ""
