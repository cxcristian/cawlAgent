"""System tools for terminal and OS interactions."""

import subprocess


def _get_default_timeout() -> int:
    """Get configurable default timeout, defaulting to 60s."""
    try:
        from cawl.config.config import get_config
        return get_config().get("executor.command_timeout", 60)
    except Exception:
        return 60


def run_command(command: str, timeout: int = None) -> str:
    """
    Execute a system command in the terminal and return output.

    Args:
        command: Shell command string to execute.
        timeout: Maximum seconds to wait before killing the process (default: from config, fallback 60).

    Returns:
        Combined STDOUT/STDERR as string, or an error message.
    """
    if timeout is None:
        timeout = _get_default_timeout()
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()  # drain pipes after kill
            return (
                f"[TIMEOUT] Command exceeded {timeout}s limit and was killed.\n"
                f"Command: {command}"
            )

        output = ""
        if stdout:
            output += f"STDOUT:\n{stdout}\n"
        if stderr:
            output += f"STDERR:\n{stderr}\n"

        if not output:
            output = "Command executed successfully (no output)."

        return output
    except Exception as e:
        return f"[ERROR] executing command: {e}"
