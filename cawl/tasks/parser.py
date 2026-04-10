"""Parser for task files (.md)."""


def parse_task_file(file_path: str) -> str:
    """Read a .md task file and return its content as plain text."""
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()
