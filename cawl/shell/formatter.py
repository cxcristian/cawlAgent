"""Output formatter for CawlShell."""

import json
import re
import textwrap
import time
from typing import Optional


class OutputFormatter:
    """Formats shell output for terminal display."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.compact = False
        self._token_count = 0
        self._start_time: Optional[float] = None

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

    def format_tool_call(self, tool_name: str, args: dict) -> str:
        """Format a tool call for display."""
        if self.verbose:
            args_str = json.dumps(args, indent=2, ensure_ascii=False)
            return f"\n{self._line('tool', f'Tool: {tool_name}')}\n{self._indent('Args:')}\n{self._indent_block(args_str)}"
        preview = json.dumps(args, ensure_ascii=False)
        if len(preview) > 100:
            preview = preview[:100] + "..."
        return f"\n{self._line('tool', f'Tool: {tool_name}')}\n{self._indent(preview)}"

    def format_tool_result(self, tool_name: str, output: str) -> str:
        """Format a tool result for display."""
        if self.verbose:
            lines = output.splitlines()[:20]
            body = "\n".join(lines)
            extra = len(output.splitlines()) - len(lines)
            suffix = f"\n{self._indent(f'... ({extra} more lines)')}" if extra > 0 else ""
            return f"{self._line('ok', f'Result: {tool_name}')}\n{self._indent_block(body)}{suffix}"
        if "\n" in output:
            lines = output.splitlines()
            preview_lines = lines[:6]
            preview = "\n".join(preview_lines)
            extra = len(lines) - len(preview_lines)
            suffix = f"\n{self._indent(f'... ({extra} lines mas)')}" if extra > 0 else ""
            return f"{self._line('ok', f'Result: {tool_name}')}\n{self._indent_block(preview)}{suffix}"
        preview = output[:200].replace("\n", " ")
        suffix = "..." if len(output) > 200 else ""
        return f"{self._line('ok', f'Result: {tool_name}')}\n{self._indent(preview + suffix)}"

    def stream_token(self, token: str):
        """Process a streaming token. Returns display string or empty."""
        self._token_count += 1
        return token

    def format_response(self, text: str) -> str:
        """Format the final LLM response."""
        if not text:
            return ""
        if self.compact:
            compact = text.replace("\n", " ").strip()
            return f"{self._line('assistant', 'CAWL')}\n{self._indent(compact)}"

        body = self._format_rich_text(text)
        return f"{self._line('assistant', 'CAWL')}\n{body}"

    def format_error(self, message: str) -> str:
        """Format an error message."""
        return f"{self._line('error', 'Error')}\n{self._indent(message)}"

    def format_status_change(self, event_type: str, message: str) -> str:
        """Format a status event for verbose display."""
        if self.verbose:
            return self._line("status", f"{event_type}: {message[:80]}")
        return ""

    def format_note(self, title: str, body: str) -> str:
        """Format a shell note or info card."""
        return f"{self._line('note', title)}\n{self._indent_block(body)}"

    def format_session_summary(
        self,
        *,
        project_path: str,
        model: str,
        context_files: int,
        message_count: int,
        verbose: bool,
        compact: bool,
    ) -> str:
        """Format a session summary block."""
        body = (
            f"Proyecto: {project_path}\n"
            f"Modelo: {model}\n"
            f"Archivos en contexto: {context_files}\n"
            f"Mensajes en sesion: {message_count}\n"
            f"Verbose: {'on' if verbose else 'off'}\n"
            f"Compacto: {'on' if compact else 'off'}"
        )
        return f"{self._line('note', 'Session')}\n{self._indent_block(body)}"

    def _line(self, kind: str, text: str) -> str:
        markers = {
            "assistant": "[CAWL]",
            "tool": "[TOOL]",
            "ok": "[OK]",
            "error": "[ERROR]",
            "status": "[STATUS]",
            "note": "[INFO]",
        }
        return f"{markers.get(kind, '[INFO]')} {text}"

    def _format_rich_text(self, text: str) -> str:
        """Render plain text with better formatting for paragraphs and code fences."""
        chunks = re.split(r"(```[\s\S]*?```)", text)
        rendered: list[str] = []
        for chunk in chunks:
            if not chunk:
                continue
            if chunk.startswith("```") and chunk.endswith("```"):
                rendered.append(self._format_code_block(chunk))
            else:
                rendered.append(self._format_paragraphs(chunk))
        return "\n\n".join(part for part in rendered if part.strip())

    def _format_code_block(self, chunk: str) -> str:
        """Render fenced code blocks with a visible header."""
        lines = chunk.strip().splitlines()
        header = lines[0][3:].strip() if lines else ""
        body_lines = lines[1:-1] if len(lines) >= 2 else []
        title = f"[CODE {header}]" if header else "[CODE]"
        body = "\n".join(body_lines) if body_lines else ""
        return f"{title}\n{self._indent_block(body)}" if body else title

    def _format_paragraphs(self, text: str) -> str:
        """Wrap prose but preserve bullets, headings and existing short structure."""
        paragraphs = text.splitlines()
        rendered: list[str] = []
        for line in paragraphs:
            stripped = line.rstrip()
            if not stripped:
                rendered.append("")
                continue
            if stripped.startswith(("- ", "* ", "|", "#")) or re.match(r"^\d+\.\s", stripped):
                rendered.append(stripped)
                continue
            wrapped = textwrap.wrap(stripped, width=96, replace_whitespace=False)
            rendered.extend(wrapped or [""])
        return "\n".join(rendered).strip()

    def _indent(self, text: str) -> str:
        return f"  {text}"

    def _indent_block(self, text: str) -> str:
        return "\n".join(self._indent(line) for line in text.splitlines())
