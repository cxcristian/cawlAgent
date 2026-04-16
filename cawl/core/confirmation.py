"""
Centralized command confirmation system for Cawl.
Provides consistent confirmation UI across CLI, Shell, and GUI modes.
"""

from enum import Enum
from typing import Optional, Dict
from cawl.core.command_risk import (
    classify_command, 
    get_command_details, 
    format_risk_display,
    RiskLevel
)


class ConfirmationResponse(Enum):
    """Possible responses to command confirmation."""
    YES = "yes"              # Execute this command
    ALWAYS = "always"        # Execute all commands for this session
    NO = "no"                # Skip this command
    DETAILS = "details"      # Show more details
    EDIT = "edit"            # Edit the command
    BATCH = "batch"          # Execute all remaining without asking
    SKIP_ALL = "skip_all"    # Skip all remaining commands


class ExecutionMode(Enum):
    """Execution modes for command running."""
    INTERACTIVE = "interactive"  # Ask before each command (default)
    TRUSTED = "trusted"          # Execute without asking
    DRY_RUN = "dry_run"          # Show but don't execute
    SAFE_ONLY = "safe_only"      # Auto-execute only low-risk commands


# Session state for confirmation system
class ConfirmationState:
    """Maintains session-wide confirmation state."""
    
    def __init__(self):
        self.always_run = False
        self.batch_mode = False
        self.skip_all = False
        self.execution_mode = ExecutionMode.INTERACTIVE
        self.command_history = []
        
    def reset(self):
        """Reset session state."""
        self.always_run = False
        self.batch_mode = False
        self.skip_all = False
        
    def should_execute(self, command: str) -> bool:
        """
        Quick check if command should execute based on session state.
        
        Args:
            command: The command to check
            
        Returns:
            True if command should execute without confirmation
        """
        if self.skip_all:
            return False
        if self.always_run or self.batch_mode:
            return True
        if self.execution_mode == ExecutionMode.TRUSTED:
            return True
        if self.execution_mode == ExecutionMode.SAFE_ONLY:
            risk_level, _ = classify_command(command)
            return risk_level == RiskLevel.LOW
        return False


# Global confirmation state (shared across execution modes)
_global_state = ConfirmationState()


def get_confirmation_state() -> ConfirmationState:
    """Get the global confirmation state."""
    return _global_state


def reset_confirmation_state():
    """Reset the global confirmation state."""
    _global_state.reset()


def initialize_confirmation_from_config():
    """Initialize confirmation state from config."""
    try:
        from cawl.config.config import get_config
        config = get_config()
        mode_str = config.get("confirmation.execution_mode", "interactive")
        try:
            mode = ExecutionMode(mode_str.lower())
            _global_state.execution_mode = mode
        except ValueError:
            pass  # Keep default
    except Exception:
        pass  # Keep defaults


def confirm_command_cli(
    command: str,
    working_dir: str = None,
    timeout: int = 60,
    state: ConfirmationState = None
) -> tuple[ConfirmationResponse, Optional[str]]:
    """
    Confirm command execution in CLI mode.
    
    Displays comprehensive information and waits for user input.
    
    Args:
        command: The command to execute
        working_dir: Working directory
        timeout: Command timeout
        state: Confirmation state (uses global if None)
        
    Returns:
        Tuple of (response, edited_command) where edited_command is only
        set if user chose to edit the command
    """
    if state is None:
        state = _global_state
    
    # Check if we should auto-execute based on state
    if state.should_execute(command):
        return ConfirmationResponse.YES, None
    
    # Check execution mode
    if state.execution_mode == ExecutionMode.DRY_RUN:
        print(f"\n[DRY RUN] Would execute: {command}")
        return ConfirmationResponse.NO, None
    
    # Get command details
    details = get_command_details(command, working_dir, timeout)
    risk_level = details["risk_level"]
    
    # Display confirmation prompt
    print()
    print("─" * 60)
    print(f"⚡ Comando propuesto: {command}")
    print(f"   Directorio: {details['working_dir']}")
    print(f"   Timeout: {details['timeout']}s | Riesgo: {format_risk_display(risk_level)}")
    print(f"   Razón: {details['reason']}")
    
    if details['has_pipes']:
        print("   ⚠ Advertencia: Comando usa pipes (|)")
    if details['has_redirect']:
        print("   ⚠ Advertencia: Comando usa redirección (>)")
    
    print("─" * 60)
    print("[y]es  [a]lways  [n]o  [d]etails  [e]dit  [b]atch  [s]kip all")
    
    while True:
        try:
            choice = input("→ ").strip().lower()
            
            if choice in ["y", "yes"]:
                return ConfirmationResponse.YES, None
            elif choice in ["a", "always"]:
                state.always_run = True
                return ConfirmationResponse.ALWAYS, None
            elif choice in ["n", "no"]:
                return ConfirmationResponse.NO, None
            elif choice in ["d", "details"]:
                _show_command_details_cli(details)
                print("\n[y]es  [a]lways  [n]o  [d]etails  [e]dit  [b]atch  [s]kip all")
                continue
            elif choice in ["e", "edit"]:
                print(f"Comando actual: {command}")
                edited = input("Nuevo comando (o Enter para cancelar): ").strip()
                if edited:
                    return ConfirmationResponse.EDIT, edited
                else:
                    print("[y]es  [a]lways  [n]o  [d]etails  [e]dit  [b]atch  [s]kip all")
                    continue
            elif choice in ["b", "batch"]:
                state.batch_mode = True
                return ConfirmationResponse.BATCH, None
            elif choice in ["s", "skip", "skip all", "skip_all"]:
                state.skip_all = True
                return ConfirmationResponse.SKIP_ALL, None
            else:
                print("Opción no válida. Use: y, a, n, d, e, b, s")
        except (EOFError, KeyboardInterrupt):
            print("\nInterrumpido por el usuario")
            return ConfirmationResponse.NO, None


def _show_command_details_cli(details: Dict):
    """Show detailed command information in CLI."""
    print("\n" + "═" * 60)
    print("DETALLES DEL COMANDO")
    print("═" * 60)
    print(f"Comando:     {details['command']}")
    print(f"Tipo:        {details['command_type']}")
    print(f"Directorio:  {details['working_dir']}")
    print(f"Timeout:     {details['timeout']}s")
    print(f"Riesgo:      {details['risk_label']}")
    print(f"Razón:       {details['reason']}")
    print(f"Pipes:       {'Sí' if details['has_pipes'] else 'No'}")
    print(f"Redirección: {'Sí' if details['has_redirect'] else 'No'}")
    print("═" * 60)


def confirm_command_shell(
    command: str,
    working_dir: str = None,
    timeout: int = 60,
    state: ConfirmationState = None,
    use_prompt_toolkit: bool = True
) -> tuple[ConfirmationResponse, Optional[str]]:
    """
    Confirm command execution in CawlShell mode.
    Uses prompt_toolkit for enhanced UX if available.
    
    Args:
        command: The command to execute
        working_dir: Working directory
        timeout: Command timeout
        state: Confirmation state (uses global if None)
        use_prompt_toolkit: Whether to use prompt_toolkit features
        
    Returns:
        Tuple of (response, edited_command)
    """
    if state is None:
        state = _global_state
    
    # Check if we should auto-execute
    if state.should_execute(command):
        return ConfirmationResponse.YES, None
    
    if state.execution_mode == ExecutionMode.DRY_RUN:
        print(f"\n[DRY RUN] Would execute: {command}")
        return ConfirmationResponse.NO, None
    
    details = get_command_details(command, working_dir, timeout)
    risk_level = details["risk_level"]
    
    # Use prompt_toolkit if available and requested
    if use_prompt_toolkit:
        try:
            from prompt_toolkit import prompt

            print(f"\n{'─' * 60}")
            print(f"⚡ Comando: {command}")
            print(f"   Riesgo: {details['risk_label']}")
            print(f"   Timeout: {details['timeout']}s | Dir: {details['working_dir']}")
            print(f"{'─' * 60}")
            print("Opciones: y=yes, a=always, n=no, d=details, e=edit, b=batch, s=skip all")

            answer = prompt("→ ").strip().lower()

            return _parse_shell_response(answer, state, command)
        except ImportError:
            pass  # Fall back to standard input
    
    # Standard input fallback
    return confirm_command_cli(command, working_dir, timeout, state)


def _parse_shell_response(
    answer: str,
    state: ConfirmationState,
    command: str
) -> tuple[ConfirmationResponse, Optional[str]]:
    """Parse response from shell prompt."""
    if answer in ["y", "yes"]:
        return ConfirmationResponse.YES, None
    elif answer in ["a", "always"]:
        state.always_run = True
        return ConfirmationResponse.ALWAYS, None
    elif answer in ["n", "no"]:
        return ConfirmationResponse.NO, None
    elif answer in ["d", "details"]:
        # For now, just re-prompt (details shown in prompt)
        return ConfirmationResponse.NO, None
    elif answer in ["e", "edit"]:
        # Would need another prompt, for now return NO
        return ConfirmationResponse.NO, None
    elif answer in ["b", "batch"]:
        state.batch_mode = True
        return ConfirmationResponse.BATCH, None
    elif answer in ["s", "skip", "skip all"]:
        state.skip_all = True
        return ConfirmationResponse.SKIP_ALL, None
    else:
        return ConfirmationResponse.NO, None


def should_show_confirmation(command: str, state: ConfirmationState = None) -> bool:
    """
    Check if confirmation should be shown for a command.
    
    Args:
        command: The command to check
        state: Confirmation state
        
    Returns:
        True if confirmation should be displayed
    """
    if state is None:
        state = _global_state
    
    return not state.should_execute(command)


def confirm_command_ui(
    command: str,
    working_dir: str = None,
    timeout: int = 60,
    state: ConfirmationState = None,
    parent_window = None
) -> tuple[ConfirmationResponse, Optional[str]]:
    """
    Confirm command execution in GUI mode using PyQt5 dialog.
    
    Args:
        command: The command to execute
        working_dir: Working directory
        timeout: Command timeout
        state: Confirmation state (uses global if None)
        parent_window: Parent PyQt5 window
        
    Returns:
        Tuple of (response, edited_command)
    """
    if state is None:
        state = _global_state
    
    # Check if we should auto-execute
    if state.should_execute(command):
        return ConfirmationResponse.YES, None
    
    if state.execution_mode == ExecutionMode.DRY_RUN:
        # In GUI, could show a message box
        return ConfirmationResponse.NO, None
    
    try:
        from PyQt5.QtWidgets import (
            QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
            QTextEdit, QFrame, QMessageBox, QInputDialog
        )
        from PyQt5.QtCore import Qt
        from PyQt5.QtGui import QFont, QPalette, QColor
        
        details = get_command_details(command, working_dir, timeout)
        risk_level = details["risk_level"]
        
        # Create dialog
        dialog = QDialog(parent_window)
        dialog.setWindowTitle("Confirmar ejecución de comando")
        dialog.setModal(True)
        dialog.resize(500, 400)
        
        layout = QVBoxLayout()
        
        # Command display
        cmd_label = QLabel(f"Comando: {command}")
        cmd_label.setFont(QFont("Consolas", 10))
        cmd_label.setWordWrap(True)
        layout.addWidget(cmd_label)
        
        # Risk badge
        risk_frame = QFrame()
        risk_frame.setFrameStyle(QFrame.Box)
        risk_layout = QHBoxLayout()
        
        risk_colors = {
            RiskLevel.LOW: QColor(0, 128, 0),      # Green
            RiskLevel.MEDIUM: QColor(255, 165, 0),  # Orange
            RiskLevel.HIGH: QColor(255, 0, 0),     # Red
            RiskLevel.CRITICAL: QColor(128, 0, 0), # Dark Red
        }
        
        risk_label = QLabel(f"RIESGO: {details['risk_label']}")
        risk_label.setStyleSheet(f"color: {risk_colors.get(risk_level, QColor(0,0,0)).name()}; font-weight: bold;")
        risk_layout.addWidget(risk_label)
        risk_layout.addStretch()
        risk_frame.setLayout(risk_layout)
        layout.addWidget(risk_frame)
        
        # Details
        details_text = QTextEdit()
        details_text.setPlainText(f"""
Directorio: {details['working_dir']}
Timeout: {details['timeout']}s
Tipo: {details['command_type']}
Razón: {details['reason']}
Pipes: {'Sí' if details['has_pipes'] else 'No'}
Redirección: {'Sí' if details['has_redirect'] else 'No'}
        """.strip())
        details_text.setReadOnly(True)
        details_text.setMaximumHeight(100)
        layout.addWidget(details_text)
        
        # Buttons
        button_layout = QHBoxLayout()
        
        yes_btn = QPushButton("Ejecutar (y)")
        yes_btn.clicked.connect(lambda: dialog.done(1))
        button_layout.addWidget(yes_btn)
        
        always_btn = QPushButton("Siempre (a)")
        always_btn.clicked.connect(lambda: dialog.done(2))
        button_layout.addWidget(always_btn)
        
        no_btn = QPushButton("No (n)")
        no_btn.clicked.connect(lambda: dialog.done(3))
        button_layout.addWidget(no_btn)
        
        edit_btn = QPushButton("Editar (e)")
        edit_btn.clicked.connect(lambda: dialog.done(4))
        button_layout.addWidget(edit_btn)
        
        batch_btn = QPushButton("Batch (b)")
        batch_btn.clicked.connect(lambda: dialog.done(5))
        button_layout.addWidget(batch_btn)
        
        skip_btn = QPushButton("Skip All (s)")
        skip_btn.clicked.connect(lambda: dialog.done(6))
        button_layout.addWidget(skip_btn)
        
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        
        result = dialog.exec_()
        
        if result == 1:  # Yes
            return ConfirmationResponse.YES, None
        elif result == 2:  # Always
            state.always_run = True
            return ConfirmationResponse.ALWAYS, None
        elif result == 3:  # No
            return ConfirmationResponse.NO, None
        elif result == 4:  # Edit
            edited, ok = QInputDialog.getText(dialog, "Editar comando", "Nuevo comando:", text=command)
            if ok and edited.strip():
                return ConfirmationResponse.EDIT, edited.strip()
            return ConfirmationResponse.NO, None
        elif result == 5:  # Batch
            state.batch_mode = True
            return ConfirmationResponse.BATCH, None
        elif result == 6:  # Skip All
            state.skip_all = True
            return ConfirmationResponse.SKIP_ALL, None
        else:
            return ConfirmationResponse.NO, None
            
    except ImportError:
        # Fall back to CLI if PyQt5 not available
        return confirm_command_cli(command, working_dir, timeout, state)


def set_execution_mode(mode: ExecutionMode):
    """Set the global execution mode."""
    _global_state.execution_mode = mode


def get_execution_mode() -> ExecutionMode:
    """Get the current execution mode."""
    return _global_state.execution_mode
