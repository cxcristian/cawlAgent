"""System tools for terminal and OS interactions."""

import os
import subprocess
import threading
import sys


def _get_default_timeout() -> int:
    """Get configurable default timeout, defaulting to 60s."""
    try:
        from cawl.config.config import get_config
        return get_config().get("executor.command_timeout", 60)
    except Exception:
        return 60


def _stream_output(process: subprocess.Popen, buffer: list, lock: threading.Lock, done: threading.Event):
    """Read and stream stdout/stderr line by line to console in real time."""
    def _reader(stream):
        try:
            for line in iter(stream.readline, ""):
                with lock:
                    buffer.append(line)
                # Print to console in real time
                sys.stdout.write(line)
                sys.stdout.flush()
        except Exception:
            pass
        finally:
            try:
                stream.close()
            except Exception:
                pass

    stdout_thread = threading.Thread(target=_reader, args=(process.stdout,), daemon=True)
    stderr_thread = threading.Thread(target=_reader, args=(process.stderr,), daemon=True)
    stdout_thread.start()
    stderr_thread.start()

    # Wait until both reader threads finish
    stdout_thread.join()
    stderr_thread.join()
    done.set()


def run_command(command: str, timeout: int = None) -> str:
    """
    Execute a system command in the terminal and return output.

    Output is streamed to the console in real time so the user can see
    progress of long-running commands (npm run build, pip install, etc.).

    Args:
        command: Shell command string to execute.
        timeout: Maximum seconds to wait before killing the process (default: from config, fallback 60).

    Returns:
        Combined STDOUT/STDERR as string, or an error message.
    """
    if timeout is None:
        timeout = _get_default_timeout()

    # Basic sanitization: reject commands with known dangerous patterns
    _DANGEROUS_PATTERNS = ["$((", "`", "${", "|&", ";&", "\\x" ]
    for pat in _DANGEROUS_PATTERNS:
        if pat in command:
            return f"[ERROR] Command contains dangerous pattern '{pat}' and was blocked."

    try:
        process = subprocess.Popen(
            command,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # merge stderr into stdout for unified streaming
            text=True,
            bufsize=1,  # line-buffered
        )

        output_buffer: list[str] = []
        buffer_lock = threading.Lock()
        done_event = threading.Event()

        stream_thread = threading.Thread(
            target=_stream_output,
            args=(process, output_buffer, buffer_lock, done_event),
            daemon=True,
        )
        stream_thread.start()

        # Wait for process to finish or timeout
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_tree(process)
            # Give stream thread a moment to drain remaining output
            done_event.wait(timeout=2)
            stream_thread.join(timeout=3)
            full_output = "".join(output_buffer)
            timeout_msg = (
                f"[TIMEOUT] Command exceeded {timeout}s limit and was killed.\n"
                f"Command: {command}\n"
            )
            if full_output:
                timeout_msg += f"Output before timeout:\n{full_output}"
            else:
                timeout_msg += "(no output captured before timeout)"
            return timeout_msg

        # Wait for stream thread to finish reading all output
        done_event.wait(timeout=5)
        stream_thread.join(timeout=5)

        full_output = "".join(output_buffer).strip()

        if not full_output:
            return "Command executed successfully (no output)."

        return full_output
    except Exception as e:
        return f"[ERROR] executing command: {e}"


def _kill_process_tree(process: subprocess.Popen):
    """Kill a process and its entire process tree."""
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                capture_output=True, timeout=5,
            )
        else:
            import signal
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    except Exception:
        process.kill()
