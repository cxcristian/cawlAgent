"""
Tool registry mapping tool names to their implementations.
Includes all rich tools: read_file, write_file, list_files,
grep_search, glob_files, and run_command.
"""

from cawl.tools.file_tools import read_file, write_file, list_files, grep_search, glob_files
from cawl.tools.system_tools import run_command

TOOLS = {
    "read_file": read_file,
    "write_file": write_file,
    "list_files": list_files,
    "grep_search": grep_search,
    "glob_files": glob_files,
    "run_command": run_command,
}

TOOL_DESCRIPTIONS = (
    "- read_file(path: str, offset: int = None, limit: int = None): Read file content. "
    "Use offset/limit to read specific line ranges.\n"
    "- write_file(path: str, content: str, mode: str = 'write'): Write to a file. "
    "mode='append' to add to end.\n"
    "- list_files(path: str, max_depth: int = 1, show_hidden: bool = False): "
    "List files and directories at a path.\n"
    "- grep_search(pattern: str, path: str = '.', glob: str = None, limit: int = 50): "
    "Search for regex pattern across files.\n"
    "- glob_files(pattern: str, path: str = '.'): Find files by glob pattern "
    "(e.g. '**/*.py').\n"
    "- run_command(command: str): Execute a terminal command (bash, cmd, etc.)."
)


def get_tool(name: str):
    """Retrieve a tool function by name, or None if not found."""
    return TOOLS.get(name)
