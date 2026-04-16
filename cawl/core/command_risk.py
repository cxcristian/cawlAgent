"""
Command risk classification system for Cawl.
Analyzes commands to determine their risk level and provides appropriate warnings.
"""

import re
from enum import Enum
from typing import Dict, List, Tuple


class RiskLevel(Enum):
    """Risk levels for command execution."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


# Risk color codes for terminal output
RISK_COLORS = {
    RiskLevel.LOW: "\033[92m",      # Green
    RiskLevel.MEDIUM: "\033[93m",   # Yellow
    RiskLevel.HIGH: "\033[91m",     # Red
    RiskLevel.CRITICAL: "\033[91m\033[1m",  # Bold Red
}

RISK_ICONS = {
    RiskLevel.LOW: "✓",
    RiskLevel.MEDIUM: "⚠",
    RiskLevel.HIGH: "⚠",
    RiskLevel.CRITICAL: "☠",
}


# Commands classified by risk level
LOW_RISK_COMMANDS = {
    # Directory listing
    "dir", "ls", "tree", "find", "glob",
    # File reading
    "cat", "type", "less", "more", "head", "tail", "wc",
    # System info
    "uname", "hostname", "whoami", "pwd", "cd",
    # Version checks
    "python --version", "node --version", "npm --version", "git --version",
    # Safe git operations
    "git status", "git log", "git branch", "git remote", "git tag",
    # Network info (read-only)
    "ipconfig", "ifconfig", "netstat",
    # Date/time
    "date", "time",
}

MEDIUM_RISK_COMMANDS = {
    # Build/run commands
    "python", "node", "npm run", "make", "cmake", "cargo run",
    # Git operations (safe)
    "git add", "git commit", "git push", "git pull", "git fetch", "git merge",
    # Package management (install)
    "npm install", "pip install", "cargo build",
    # Compilation
    "gcc", "g++", "clang", "javac",
    # Testing
    "pytest", "unittest", "npm test", "jest", "mocha",
    # File operations (copy/move)
    "cp", "copy", "mv", "move", "xcopy", "robocopy",
}

HIGH_RISK_COMMANDS = {
    # Destructive file operations
    "rm", "del", "rmdir", "rd", "erase",
    # Git operations (potentially destructive)
    "git reset", "git checkout", "git revert", "git clean",
    # Force operations
    "chmod", "chown", "icacls",
    # System operations
    "shutdown", "restart", "kill", "taskkill",
    # Disk operations
    "format", "diskpart",
}

CRITICAL_PATTERNS = [
    # Recursive force delete
    r"rm\s+(-rf|--recursive.*--force|--force.*--recursive)",
    r"del\s+/s/q",
    r"rmdir\s+/s/q",
    # Format disk
    r"format\s+",
    # Database drops
    r"drop\s+(database|table)",
    # Sudo with dangerous commands
    r"sudo\s+(rm|del|shutdown|reboot|mkfs)",
]


def classify_command(command: str) -> Tuple[RiskLevel, str]:
    """
    Classify a command's risk level and provide a reason.
    
    Args:
        command: The command string to classify
        
    Returns:
        Tuple of (risk_level, reason)
    """
    command_stripped = command.strip().lower()
    
    # Check critical patterns first
    for pattern in CRITICAL_PATTERNS:
        if re.search(pattern, command_stripped, re.IGNORECASE):
            return RiskLevel.CRITICAL, "This command can cause irreversible data loss or system damage"
    
    # Check for pipes and redirections (increases risk)
    has_pipes = "|" in command_stripped
    has_redirect = ">" in command_stripped or ">>" in command_stripped
    
    # Check for dangerous flags
    has_force = "-f" in command_stripped or "--force" in command_stripped
    has_recursive = "-r" in command_stripped or "--recursive" in command_stripped
    
    # Match against known commands
    first_word = command_stripped.split()[0] if command_stripped else ""
    
    # Check exact matches first
    for cmd in LOW_RISK_COMMANDS:
        if command_stripped == cmd or command_stripped.startswith(cmd + " "):
            if has_pipes or has_redirect:
                return RiskLevel.MEDIUM, "Command uses pipes or redirections"
            return RiskLevel.LOW, "Read-only operation with minimal risk"
    
    for cmd in MEDIUM_RISK_COMMANDS:
        if command_stripped == cmd or command_stripped.startswith(cmd + " "):
            reason = "Executes code or modifies files"
            if has_force or has_recursive:
                reason += " with force/recursive flags"
            return RiskLevel.MEDIUM, reason
    
    for cmd in HIGH_RISK_COMMANDS:
        if command_stripped == cmd or command_stripped.startswith(cmd + " "):
            reason = "Can delete or modify important files/system settings"
            if has_force:
                reason += " (force flag detected)"
            return RiskLevel.HIGH, reason
    
    # Unknown commands default to medium risk
    if not first_word:
        return RiskLevel.MEDIUM, "Unknown command"
    
    return RiskLevel.MEDIUM, f"Command '{first_word}' not in risk database"


def get_command_details(command: str, working_dir: str = None, timeout: int = 60) -> Dict:
    """
    Get detailed information about a command for display in confirmation dialog.
    
    Args:
        command: The command string
        working_dir: Working directory for execution
        timeout: Command timeout in seconds
        
    Returns:
        Dictionary with command details
    """
    risk_level, reason = classify_command(command)
    
    # Determine command type
    command_type = "unknown"
    if any(cmd in command.lower() for cmd in ["rm", "del", "rmdir", "rd", "erase"]):
        command_type = "destructive"
    elif any(cmd in command.lower() for cmd in ["read", "cat", "type", "ls", "dir", "find"]):
        command_type = "read-only"
    elif any(cmd in command.lower() for cmd in ["python", "node", "npm", "make"]):
        command_type = "execution"
    elif "git" in command.lower():
        command_type = "version-control"
    elif any(cmd in command.lower() for cmd in ["cp", "copy", "mv", "move"]):
        command_type = "file-operation"
    
    return {
        "command": command,
        "working_dir": working_dir or "current directory",
        "timeout": timeout,
        "risk_level": risk_level,
        "risk_label": risk_level.value.upper(),
        "reason": reason,
        "command_type": command_type,
        "has_pipes": "|" in command,
        "has_redirect": ">" in command,
    }


def format_risk_display(risk_level: RiskLevel, use_color: bool = True) -> str:
    """
    Format risk level for display in terminal.
    
    Args:
        risk_level: The risk level to display
        use_color: Whether to include ANSI color codes
        
    Returns:
        Formatted string for terminal display
    """
    icon = RISK_ICONS[risk_level]
    label = risk_level.value.upper()
    
    if use_color:
        color = RISK_COLORS[risk_level]
        reset = "\033[0m"
        return f"{color}{icon} {label}{reset}"
    
    return f"{icon} {label}"
