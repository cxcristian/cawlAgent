"""System tools for terminal and OS interactions."""

import subprocess


def run_command(command: str) -> str:
    """Execute a system command in the terminal and return output."""
    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, stderr = process.communicate()

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
