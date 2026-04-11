"""
File tools for reading, writing, listing, and searching files.
Rich implementations from the original cawl_agent with full parameter support.
"""

import os
import re
import glob as glob_module
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed


def _get_max_read_size() -> int:
    """Get configurable max read size, defaulting to 100 KB."""
    try:
        from cawl.config.config import get_config
        return get_config().get("tools.max_read_size", 100 * 1024)
    except Exception:
        return 100 * 1024


# File extensions considered safe to read as text
TEXT_EXTENSIONS = {
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h", ".hpp",
    ".cs", ".go", ".rs", ".rb", ".php", ".swift", ".kt", ".scala", ".sh",
    ".bash", ".zsh", ".fish", ".lua", ".pl", ".pm", ".r", ".m", ".mm",
    ".html", ".htm", ".css", ".scss", ".sass", ".less", ".vue", ".svelte",
    ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".xml",
    ".csv", ".env", ".sql",
    ".md", ".txt", ".rst", ".log",
    ".jinja", ".jinja2", ".tpl", ".mustache", ".handlebars", ".hbs",
    ".graphql", ".proto", ".tf", ".dockerfile", ".gitignore", ".gitattributes",
}


def _is_text_file(file_path: Path) -> bool:
    """Determine if a file is likely text-based."""
    if file_path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(512)
        chunk.decode("utf-8")
        return True
    except (UnicodeDecodeError, OSError):
        return False


def _truncate_content(content: str, max_size: int = None) -> tuple[str, bool]:
    """Truncate content if it exceeds max size. Returns (content, was_truncated)."""
    if max_size is None:
        max_size = _get_max_read_size()
    if len(content) <= max_size:
        return content, False
    return (
        content[:max_size] + f"\n\n... [TRUNCATED: {len(content) - max_size} more characters]",
        True,
    )


def _format_size(size_bytes: int) -> str:
    """Format a file size in human-readable form."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def read_file(path: str, offset: Optional[int] = None, limit: Optional[int] = None) -> str:
    """
    Read and return the content of a file.

    Args:
        path: Absolute (or relative) path to the file.
        offset: 0-based line number to start reading from.
        limit: Maximum number of lines to read.

    Returns:
        File content as string, or error message.
    """
    fpath = Path(path)

    if not fpath.exists():
        return f"[ERROR] File does not exist: {path}"
    if fpath.is_dir():
        return f"[ERROR] Path is a directory, not a file: {path}"

    try:
        with open(fpath, "r", encoding="utf-8") as f:
            if offset is not None or limit is not None:
                start = offset or 0
                content = ""
                for i, line in enumerate(f):
                    if i < start:
                        continue
                    if limit is not None and i >= start + limit:
                        content += f"\n... [showing lines {start + 1}-{i} of file]"
                        break
                    content += line
            else:
                content = f.read()

        content, truncated = _truncate_content(content)
        result = f"File: {path}\n{'=' * 60}\n{content}"
        if truncated:
            max_size = _get_max_read_size()
            result += f"\n\n[CONTENT TRUNCATED: File exceeds {max_size // 1024} KB limit]"
        return result

    except UnicodeDecodeError:
        return f"[ERROR] Cannot decode file as UTF-8: {path}"
    except PermissionError:
        return f"[ERROR] Permission denied: {path}"
    except OSError as e:
        return f"[ERROR] Failed to read file: {e}"


def write_file(path: str, content: str, mode: str = "write") -> str:
    """
    Write content to a file. Creates directories if needed.

    Args:
        path: Path to the file.
        content: Content to write.
        mode: 'write' to overwrite, 'append' to add to end.

    Returns:
        Confirmation string or error message.
    """
    fpath = Path(path)
    try:
        fpath.parent.mkdir(parents=True, exist_ok=True)
        write_mode = "a" if mode == "append" else "w"
        with open(fpath, write_mode, encoding="utf-8") as f:
            f.write(content)
        action = "Written to" if mode == "write" else "Appended to"
        return f"{action} {path} ({_format_size(len(content))} written)"
    except PermissionError:
        return f"[ERROR] Permission denied: {path}"
    except OSError as e:
        return f"[ERROR] Failed to write file: {e}"


def list_files(path: str, max_depth: int = 1, show_hidden: bool = False) -> str:
    """
    List files and subdirectories within a directory.

    Args:
        path: Path to the directory.
        max_depth: Maximum depth to traverse (default: 1).
        show_hidden: Whether to include hidden files/directories.

    Returns:
        Formatted directory listing.
    """
    dir_path = Path(path)

    if not dir_path.exists():
        return f"[ERROR] Path does not exist: {path}"
    if not dir_path.is_dir():
        return f"[ERROR] Path is not a directory: {path}"

    try:
        entries = sorted(dir_path.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    except PermissionError:
        return f"[ERROR] Permission denied: {path}"

    lines = [f"Directory: {dir_path}", ""]

    for entry in entries:
        if not show_hidden and entry.name.startswith("."):
            continue
        if entry.is_dir():
            lines.append(f"[DIR]  {entry.name}/")
        else:
            size_str = _format_size(entry.stat().st_size)
            lines.append(f"[FILE] {entry.name} ({size_str})")

    if len(lines) == 2:
        lines.append("(empty directory)")

    return "\n".join(lines)


def grep_search(
    pattern: str,
    path: str = ".",
    glob: Optional[str] = None,
    limit: int = 50,
) -> str:
    """
    Search for a text pattern within files using regular expressions.

    Args:
        pattern: Regex pattern to search for.
        path: File or directory to search in.
        glob: Glob pattern to filter files (e.g. '*.py').
        limit: Maximum number of matches to return.

    Returns:
        Formatted search results.
    """
    search_path = Path(path)

    if not search_path.exists():
        return f"[ERROR] Path does not exist: {path}"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"[ERROR] Invalid regex pattern: {e}"

    if search_path.is_file():
        files_to_search = [search_path]
    else:
        if glob:
            files_to_search = list(search_path.rglob(glob))
        else:
            files_to_search = []
            for root, dirs, files in os.walk(search_path):
                for fname in files:
                    fpath = Path(root) / fname
                    if _is_text_file(fpath):
                        files_to_search.append(fpath)

    results = []
    try:
        def search_file(fpath):
            """Search for pattern in a single file."""
            file_results = []
            if not fpath.is_file() or not _is_text_file(fpath):
                return file_results
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            file_results.append((fpath, line_num, line.rstrip()))
                            if len(file_results) >= limit:
                                break
            except (UnicodeDecodeError, PermissionError, OSError):
                pass
            return file_results

        if len(files_to_search) <= 10:
            # Small number of files - sequential is fine
            for fpath in files_to_search:
                file_results = search_file(fpath)
                results.extend(file_results)
                if len(results) >= limit:
                    break
        else:
            # Large number of files - use thread pool
            max_workers = min(8, len(files_to_search))  # Cap at 8 threads
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_file = {
                    executor.submit(search_file, fpath): fpath
                    for fpath in files_to_search
                }
                
                for future in as_completed(future_to_file):
                    file_results = future.result()
                    results.extend(file_results)
                    if len(results) >= limit:
                        break
    except Exception as e:
        return f"[ERROR] Search failed: {e}"

    if not results:
        return f"No matches found for pattern '{pattern}'."

    lines = [f"Found {len(results)} match(es) for '{pattern}':", ""]
    for fpath, line_num, line_text in results:
        lines.append(f"{fpath}:{line_num}: {line_text}")
    if len(results) >= limit:
        lines.append(f"\n[Showing first {limit} matches only]")

    return "\n".join(lines)


def glob_files(pattern: str, path: str = ".") -> str:
    """
    Find files matching a glob pattern.

    Args:
        pattern: Glob pattern (e.g. '**/*.py', 'src/**/*.ts').
        path: Directory to search in.

    Returns:
        List of matching file paths.
    """
    search_path = Path(path)

    if not search_path.exists():
        return f"[ERROR] Path does not exist: {path}"

    try:
        if "**" in pattern:
            clean_pattern = pattern.lstrip("*").lstrip("/")
            matches = list(search_path.rglob(clean_pattern))
        else:
            matches = list(search_path.glob(pattern))

        if not matches:
            return f"No files matching pattern '{pattern}' in {path}"

        lines = [f"Found {len(matches)} file(s) matching '{pattern}':", ""]
        for m in sorted(matches):
            marker = "[DIR] " if m.is_dir() else "[FILE] "
            lines.append(f"{marker}{m}")

        return "\n".join(lines)

    except Exception as e:
        return f"[ERROR] Glob search failed: {e}"
