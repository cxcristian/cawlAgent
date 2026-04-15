"""
CAWL UI - Interfaz gráfica para el agente Cawl.
Tema oscuro, chat tipo burbuja, árbol de carpetas a la izquierda,
input expandible abajo.
"""

import sys
import os
import threading
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QSplitter, QTreeView, QTextEdit, QPushButton, QLabel,
    QFileSystemModel, QScrollArea, QSizePolicy, QFrame, QLineEdit,
    QFileDialog, QShortcut, QMessageBox
)
from PyQt5.QtCore import (
    Qt, QThread, pyqtSignal, QDir, QSize, QTimer, QPropertyAnimation,
    QEasingCurve
)
from PyQt5.QtGui import (
    QFont, QColor, QPalette, QTextCursor, QKeySequence, QIcon,
    QPainter, QBrush, QFontMetrics
)

# ---------------------------------------------------------------------------
# Colores / tema
# ---------------------------------------------------------------------------
BG_DARK      = "#0f1117"
BG_PANEL     = "#161b22"
BG_BUBBLE_AI = "#1e2736"
BG_BUBBLE_US = "#1f3a2a"
BG_INPUT     = "#1c2028"
BG_HEADER    = "#0d1117"
ACCENT       = "#58a6ff"
ACCENT2      = "#3fb950"
TEXT_MAIN    = "#e6edf3"
TEXT_DIM     = "#8b949e"
TEXT_FILE    = "#79c0ff"
BORDER       = "#30363d"
DANGER       = "#f85149"
WARN         = "#d29922"


STYLESHEET = f"""
QMainWindow, QWidget {{
    background-color: {BG_DARK};
    color: {TEXT_MAIN};
    font-family: 'Segoe UI', 'Inter', sans-serif;
    font-size: 13px;
}}
QSplitter::handle {{
    background-color: {BORDER};
    width: 1px;
}}
/* Árbol de archivos */
QTreeView {{
    background-color: {BG_PANEL};
    border: none;
    color: {TEXT_MAIN};
    padding: 4px;
    outline: 0;
}}
QTreeView::item {{
    padding: 3px 4px;
    border-radius: 4px;
}}
QTreeView::item:hover {{
    background-color: #21262d;
}}
QTreeView::item:selected {{
    background-color: #1f3a5f;
    color: {TEXT_MAIN};
}}
QTreeView::branch {{
    background: transparent;
}}
/* Scroll bars */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: #484f58;
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 6px;
    border-radius: 3px;
}}
QScrollBar::handle:horizontal {{
    background: #484f58;
    border-radius: 3px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
/* Input */
QTextEdit#inputBox {{
    background-color: {BG_INPUT};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT_MAIN};
    padding: 10px 12px;
    font-size: 13px;
    line-height: 1.5;
}}
QTextEdit#inputBox:focus {{
    border: 1px solid {ACCENT};
}}
/* Botones */
QPushButton#sendBtn {{
    background-color: {ACCENT};
    color: #fff;
    border: 1px solid {ACCENT};
    border-radius: 8px;
    font-weight: bold;
     
    font-size: 13px;
    padding: 0 20px;
    min-width: 80px;
}}
QPushButton#sendBtn:hover {{
    background-color: #79c0ff;
}}
QPushButton#sendBtn:pressed {{
    background-color: #388bfd;
}}
QPushButton#sendBtn:disabled {{
    background-color: #21262d;
    color: {TEXT_DIM};
}}
QPushButton#folderBtn {{
    background-color: #21262d;
    color: {TEXT_DIM};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-size: 12px;
    padding: 4px 10px;
}}
QPushButton#folderBtn:hover {{
    background-color: #30363d;
    color: {TEXT_MAIN};
}}
QPushButton#clearBtn {{
    background-color: transparent;
    color: {TEXT_DIM};
    border: none;
    font-size: 11px;
    padding: 4px 8px;
}}
QPushButton#clearBtn:hover {{
    color: {DANGER};
}}
/* Labels */
QLabel#panelTitle {{
    color: {TEXT_DIM};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 1px;
    padding: 8px 12px 4px 12px;
}}
QLabel#projectPath {{
    color: {TEXT_FILE};
    font-size: 11px;
    padding: 2px 12px 6px 12px;
    font-family: monospace;
}}
QLabel#statusBar {{
    color: {TEXT_DIM};
    font-size: 11px;
    padding: 2px 8px;
}}
/* Header */
QWidget#header {{
    background-color: {BG_HEADER};
    border-bottom: 1px solid {BORDER};
}}
QLabel#appTitle {{
    color: {ACCENT};
    font-size: 14px;
    font-weight: bold;
    letter-spacing: 2px;
    font-family: monospace;
}}
QLabel#appSub {{
    color: {TEXT_DIM};
    font-size: 11px;
}}
/* Área de chat */
QScrollArea#chatArea {{
    background-color: {BG_DARK};
    border: none;
}}
QWidget#chatContainer {{
    background-color: {BG_DARK};
}}
/* Frame del área de input */
QFrame#inputFrame {{
    background-color: {BG_PANEL};
    border-top: 1px solid {BORDER};
}}
"""


# ---------------------------------------------------------------------------
# Worker thread — llama al agente sin bloquear la UI
# ---------------------------------------------------------------------------

class AgentWorker(QThread):
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    status_update  = pyqtSignal(str, str)   # (event_type, message)
    confirm_run    = pyqtSignal(str)          # command string to confirm

    def __init__(self, message: str, history: list, system_prompt: str, model: str):
        super().__init__()
        self.message = message
        self.history = history
        self.system_prompt = system_prompt
        self.model = model
        self._run_allowed = True  # set to False by main thread if user denies

        # Load configurable constants
        from cawl.config.config import get_config
        config = get_config()
        self.max_iter = config.get("executor.max_tool_iterations", 20)

    def run(self):
        try:
            from cawl.core.llm_client import OllamaClient
            from cawl.core.status import status
            from cawl.tools.registry import get_tool

            # Subscribe to status events and forward to UI via Qt signal
            def _on_status(event_type: str, message: str):
                self.status_update.emit(event_type, message)

            status.subscribe(_on_status)

            try:
                client = OllamaClient(model=self.model)

                messages = [{"role": "system", "content": self.system_prompt}]
                messages.extend(self.history)
                messages.append({"role": "user", "content": self.message})

                MAX_ITER = self.max_iter
                for _ in range(MAX_ITER):
                    self.status_update.emit("thinking", "Razonando...")
                    response = client.chat_with_tools(messages=messages, temperature=0.1)

                    if not response["tool_calls"]:
                        self.response_ready.emit(response["content"])
                        return

                    for tool_call in response["tool_calls"]:
                        tool_name = tool_call["name"]
                        tool_args = tool_call.get("arguments", {})

                        # Confirmation gate for run_command
                        if tool_name == "run_command":
                            cmd = tool_args.get("command", str(tool_args))
                            self._run_allowed = True  # reset per-call
                            self.confirm_run.emit(cmd)
                            # Wait for main thread to set _run_allowed
                            while self.isRunning() and hasattr(self, "_waiting_confirm"):
                                QThread.msleep(50)
                            if not self._run_allowed:
                                result_str = "Command execution denied by user."
                                self.status_update.emit("tool_call", f"{tool_name} → DENIED")
                                messages.append({
                                    "role": "user",
                                    "content": f"RESULTADO de {tool_name}: {result_str}",
                                })
                                continue

                        self.status_update.emit(
                            "tool_call",
                            f"{tool_name}({str(tool_args)[:60]})"
                        )

                        func = get_tool(tool_name)
                        if func is None:
                            result_str = f"[ERROR] Unknown tool: {tool_name}"
                        else:
                            try:
                                result = func(**tool_args) if isinstance(tool_args, dict) else func(tool_args)
                                result_str = str(result)
                                preview = result_str[:80].replace("\n", " ")
                                self.status_update.emit("tool_result", f"{tool_name} → {preview}")
                            except Exception as e:
                                result_str = f"[ERROR] {e}"
                                self.status_update.emit("error", str(e)[:80])

                        messages.append({
                            "role": "user",
                            "content": f"RESULTADO de {tool_name}: {result_str}",
                        })

                self.response_ready.emit("[INFO] Máximo de iteraciones alcanzado.")

            finally:
                status.unsubscribe(_on_status)

        except ImportError:
            self.error_occurred.emit(
                "Módulo 'cawl' no encontrado.\n"
                "Instálalo con: pip install -e . (desde la raíz del proyecto)"
            )
        except Exception as e:
            self.error_occurred.emit(str(e))


# ---------------------------------------------------------------------------
# Burbuja de status (indicador de progreso en la UI)
# ---------------------------------------------------------------------------

class StatusBubble(QWidget):
    """
    Burbuja animada que muestra el estado actual del agente.
    Se actualiza en tiempo real vía señal Qt desde AgentWorker.
    """

    ICONS = {
        "thinking":    ("Razonando",     WARN),
        "planning":    ("Planificando",  ACCENT),
        "tool_call":   ("Herramienta",   "#c678dd"),
        "tool_result": ("Resultado",     ACCENT2),
        "step":        ("Paso",          ACCENT),
        "retry":       ("Reintentando",  WARN),
        "trim":        ("Comprimiendo",  WARN),
        "done":        ("Listo",         ACCENT2),
        "error":       ("Error",         DANGER),
        "agent":       ("Agente",        ACCENT),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._dots = 0

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 6, 16, 6)
        layout.setSpacing(8)

        self._icon_lbl = QLabel("○")
        self._icon_lbl.setStyleSheet(f"color: {WARN}; font-size: 13px; font-weight: bold;")
        self._icon_lbl.setFixedWidth(20)

        self._type_lbl = QLabel("Procesando")
        self._type_lbl.setStyleSheet(f"color: {WARN}; font-size: 11px; font-weight: bold; min-width: 80px;")

        self._msg_lbl = QLabel("Esperando respuesta...")
        self._msg_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px;")
        self._msg_lbl.setWordWrap(False)

        self._dots_lbl = QLabel("")
        self._dots_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 12px; min-width: 24px;")

        layout.addWidget(self._icon_lbl)
        layout.addWidget(self._type_lbl)
        layout.addWidget(self._msg_lbl, 1)
        layout.addWidget(self._dots_lbl)

        self.setStyleSheet(f"""
            StatusBubble {{
                background-color: {BG_BUBBLE_AI};
                border: 1px solid #1f6feb;
                border-radius: 8px;
            }}
        """)

    def update_status(self, event_type: str, message: str):
        label, color = self.ICONS.get(event_type, ("Procesando", WARN))
        self._icon_lbl.setStyleSheet(f"color: {color}; font-size: 13px; font-weight: bold;")
        self._type_lbl.setText(label)
        self._type_lbl.setStyleSheet(f"color: {color}; font-size: 11px; font-weight: bold; min-width: 80px;")
        # Truncate message
        display = message[:70] + ("..." if len(message) > 70 else "")
        self._msg_lbl.setText(display)

    def start_animation(self):
        self._dots = 0
        self._timer.start(400)

    def stop_animation(self):
        self._timer.stop()
        self._dots_lbl.setText("")

    def _tick(self):
        self._dots = (self._dots + 1) % 4
        self._dots_lbl.setText("." * self._dots)


# ---------------------------------------------------------------------------
# Burbuja de mensaje
# ---------------------------------------------------------------------------

class MessageBubble(QWidget):
    def __init__(self, text: str, role: str, parent=None):
        super().__init__(parent)
        self.role = role  # "user" | "assistant" | "system"
        self._build(text)

    def _build(self, text: str):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 12, 4)
        layout.setSpacing(0)

        bubble = QTextEdit()
        bubble.setReadOnly(True)
        bubble.setPlainText(text)
        bubble.setFont(QFont("Segoe UI", 12))
        bubble.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)
        bubble.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bubble.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        bubble.setLineWrapMode(QTextEdit.WidgetWidth)
        bubble.setFrameShape(QFrame.NoFrame)

        # Ajustar altura al contenido
        doc_height = int(bubble.document().size().height()) + 20
        bubble.setMinimumHeight(min(doc_height, 400))
        bubble.setMaximumHeight(max(doc_height, 60))

        if self.role == "user":
            bg = BG_BUBBLE_US
            border_color = "#2ea043"
            label_text = "Tú"
            label_color = ACCENT2
            layout.addStretch()
        elif self.role == "assistant":
            bg = BG_BUBBLE_AI
            border_color = "#1f6feb"
            label_text = "Cawl"
            label_color = ACCENT
        else:
            bg = "#1a1a2e"
            border_color = WARN
            label_text = "Sistema"
            label_color = WARN

        bubble.setStyleSheet(f"""
            QTextEdit {{
                background-color: {bg};
                color: {TEXT_MAIN};
                border: 1px solid {border_color};
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 13px;
                line-height: 1.6;
            }}
        """)

        # Contenedor con label encima
        container = QVBoxLayout()
        container.setSpacing(3)

        lbl = QLabel(label_text)
        lbl.setStyleSheet(f"color: {label_color}; font-size: 11px; font-weight: bold; padding: 0;")

        if self.role == "user":
            lbl.setAlignment(Qt.AlignRight)

        container.addWidget(lbl)
        container.addWidget(bubble)

        if self.role == "user":
            layout.addLayout(container)
        else:
            layout.addLayout(container)
            layout.addStretch()


# ---------------------------------------------------------------------------
# Panel de chat
# ---------------------------------------------------------------------------

class ChatPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("chatContainer")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 8, 0, 8)
        self._layout.setSpacing(6)
        self._layout.addStretch()

    def add_message(self, text: str, role: str):
        bubble = MessageBubble(text, role)
        # Insertar antes del stretch final
        self._layout.insertWidget(self._layout.count() - 1, bubble)

    def clear(self):
        while self._layout.count() > 1:
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()


# ---------------------------------------------------------------------------
# Input expandible
# ---------------------------------------------------------------------------

class ExpandableInput(QTextEdit):
    send_requested = pyqtSignal()

    MIN_HEIGHT = 44
    MAX_HEIGHT = 220

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("inputBox")
        self.setPlaceholderText("Escribe tu mensaje aquí... (Enter para enviar, Shift+Enter para nueva línea)")
        self.setFont(QFont("Segoe UI", 13))
        self.setMinimumHeight(self.MIN_HEIGHT)
        self.setMaximumHeight(self.MAX_HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.document().contentsChanged.connect(self._adjust_height)

    def _adjust_height(self):
        doc_height = int(self.document().size().height()) + 24
        new_height = max(self.MIN_HEIGHT, min(doc_height, self.MAX_HEIGHT))
        self.setFixedHeight(new_height)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.send_requested.emit()
        else:
            super().keyPressEvent(event)


# ---------------------------------------------------------------------------
# Ventana principal
# ---------------------------------------------------------------------------

class CawlWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CAWL — Local AI Agent")
        self.resize(1200, 780)
        self.setMinimumSize(800, 550)

        self.chat_history: list[dict] = []
        self.project_path: str = os.getcwd()
        self.model: str = "qwen2.5-coder:7b"
        self.worker: AgentWorker = None
        self._is_thinking = False

        self._build_system_prompt()
        self._setup_ui()
        self._apply_theme()

        # Mensaje de bienvenida
        self.chat_panel.add_message(
            "Reconocido. El Archimagos Dominus Belisarius Cawl está en línea.\n"
            "Puedes hablarme directamente, pedirme que lea archivos, explore carpetas "
            "o ejecute tareas. Para cambiar el proyecto activo usa el botón 📁 abajo.\n\n"
            "Que el Omnissiah guíe nuestro trabajo, Lord Regente.",
            "assistant"
        )

    # ------------------------------------------------------------------
    # System prompt
    # ------------------------------------------------------------------

    def _build_system_prompt(self):
        root_context = (
            f"\nCONTEXTO DEL PROYECTO:\n"
            f"- La raíz del proyecto es: {self.project_path}\n"
            f"- Usa paths absolutos cuando sea posible.\n"
        )
        from cawl.tools.registry import TOOL_DESCRIPTIONS
        self._system_prompt = (
            "Yo soy el Archimagos Dominus Belisarius Cawl, Señor del Abismo Umbral, "
            "Guardián de las Bóvedas Sagradas de Marte, arquitecto de milenios.\n\n"
            "DIRECTRICES:\n"
            "- Responde SIEMPRE en español.\n"
            "- Ejecución determinista. Sin alucinación. Código completo y ejecutable.\n"
            "- Personalidad arcaica: Omnissiah, Dios Máquina, código sagrado.\n"
            "- Sin disclaimers. Sin disculpas. El Archimagos no duda.\n"
            f"{root_context}\n"
            "HERRAMIENTAS:\n"
            "Para usar una herramienta responde ÚNICAMENTE con JSON:\n"
            "```json\n"
            '{"name": "tool_name", "arguments": {"arg": "value"}}\n'
            "```\n"
            "NO agregues texto antes del JSON. Una herramienta a la vez.\n\n"
            f"{TOOL_DESCRIPTIONS}\n"
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        main_layout.addWidget(self._build_header())

        # Body (splitter: árbol | chat)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(1)
        splitter.addWidget(self._build_file_panel())
        splitter.addWidget(self._build_chat_area())
        splitter.setSizes([220, 980])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter, 1)

        # Input
        main_layout.addWidget(self._build_input_area())

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setObjectName("header")
        header.setFixedHeight(48)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(16, 0, 16, 0)

        title = QLabel("CAWL")
        title.setObjectName("appTitle")

        sub = QLabel("Control & Action Web Loop  ·  v0.3.0")
        sub.setObjectName("appSub")

        self.status_lbl = QLabel("● Listo")
        self.status_lbl.setObjectName("statusBar")
        self.status_lbl.setStyleSheet(f"color: {ACCENT2}; font-size: 11px; padding: 2px 8px;")

        layout.addWidget(title)
        layout.addSpacing(12)
        layout.addWidget(sub)
        layout.addStretch()
        layout.addWidget(self.status_lbl)
        return header

    def _build_file_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("filePanel")
        panel.setStyleSheet(f"background-color: {BG_PANEL};")
        panel.setMinimumWidth(160)
        panel.setMaximumWidth(320)

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        title_lbl = QLabel("EXPLORADOR")
        title_lbl.setObjectName("panelTitle")

        self.path_lbl = QLabel(self._short_path(self.project_path))
        self.path_lbl.setObjectName("projectPath")
        self.path_lbl.setWordWrap(True)

        self.fs_model = QFileSystemModel()
        self.fs_model.setRootPath(self.project_path)
        self.fs_model.setFilter(QDir.AllDirs | QDir.Files | QDir.NoDotAndDotDot)

        self.tree = QTreeView()
        self.tree.setModel(self.fs_model)
        self.tree.setRootIndex(self.fs_model.index(self.project_path))
        self.tree.setHeaderHidden(True)
        # Solo mostrar columna de nombre
        for col in range(1, self.fs_model.columnCount()):
            self.tree.hideColumn(col)
        self.tree.setIndentation(14)
        self.tree.setAnimated(True)

        layout.addWidget(title_lbl)
        layout.addWidget(self.path_lbl)
        layout.addWidget(self.tree, 1)
        return panel

    def _build_chat_area(self) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.chat_panel = ChatPanel()

        self.scroll_area = QScrollArea()
        self.scroll_area.setObjectName("chatArea")
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setWidget(self.chat_panel)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        layout.addWidget(self.scroll_area, 1)
        return wrapper

    def _build_input_area(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("inputFrame")
        frame.setStyleSheet(f"background-color: {BG_PANEL}; border-top: 1px solid {BORDER};")

        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 10, 12, 10)
        outer.setSpacing(8)

        # Fila de controles superiores
        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(6)

        self.folder_btn = QPushButton("📁  Cambiar proyecto")
        self.folder_btn.setObjectName("folderBtn")
        self.folder_btn.clicked.connect(self._pick_folder)

        self.clear_btn = QPushButton("Limpiar chat")
        self.clear_btn.setObjectName("clearBtn")
        self.clear_btn.clicked.connect(self._clear_chat)

        self.model_lbl = QLabel(f"Modelo: {self.model}")
        self.model_lbl.setStyleSheet(f"color: {TEXT_DIM}; font-size: 11px;")

        ctrl_row.addWidget(self.folder_btn)
        ctrl_row.addWidget(self.clear_btn)
        ctrl_row.addStretch()
        ctrl_row.addWidget(self.model_lbl)

        # Fila de input + botón
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.input_box = ExpandableInput()
        self.input_box.send_requested.connect(self._send_message)

        self.send_btn = QPushButton("Enviar")
        self.send_btn.setObjectName("sendBtn")
        self.send_btn.setFixedSize(88, 44)
        self.send_btn.clicked.connect(self._send_message)

        input_row.addWidget(self.input_box, 1)
        input_row.addWidget(self.send_btn, 0, Qt.AlignBottom)

        outer.addLayout(ctrl_row)
        outer.addLayout(input_row)
        return frame

    # ------------------------------------------------------------------
    # Tema
    # ------------------------------------------------------------------

    def _apply_theme(self):
        self.setStyleSheet(STYLESHEET)
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(BG_DARK))
        palette.setColor(QPalette.WindowText, QColor(TEXT_MAIN))
        palette.setColor(QPalette.Base, QColor(BG_PANEL))
        palette.setColor(QPalette.Text, QColor(TEXT_MAIN))
        self.setPalette(palette)

    # ------------------------------------------------------------------
    # Lógica
    # ------------------------------------------------------------------

    def _send_message(self):
        if self._is_thinking:
            return

        text = self.input_box.toPlainText().strip()
        if not text:
            return

        self.input_box.clear()
        self.chat_panel.add_message(text, "user")
        self._scroll_to_bottom()

        self.chat_history.append({"role": "user", "content": text})

        self._set_thinking(True)
        self._show_status_bubble()

        self.worker = AgentWorker(
            message=text,
            history=self.chat_history[:-1],
            system_prompt=self._system_prompt,
            model=self.model,
        )
        self.worker.response_ready.connect(self._on_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.status_update.connect(self._on_status_update)
        self.worker.confirm_run.connect(self._on_confirm_run)
        self.worker.start()

    def _on_confirm_run(self, command: str):
        """Show a modal confirmation dialog for run_command in the UI."""
        self.worker._waiting_confirm = True
        reply = QMessageBox.question(
            self,
            "Confirmar ejecución de comando",
            f"El agente quiere ejecutar:\n\n<code>{command}</code>\n\n¿Autorizar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        self.worker._run_allowed = reply == QMessageBox.Yes
        del self.worker._waiting_confirm

    def _show_status_bubble(self):
        """Insert an animated status bubble into the chat panel."""
        self._status_bubble = StatusBubble()
        self._status_bubble.start_animation()
        # Insert before the stretch at the end
        self.chat_panel._layout.insertWidget(
            self.chat_panel._layout.count() - 1,
            self._status_bubble
        )
        self._scroll_to_bottom()

    def _hide_status_bubble(self):
        """Remove the status bubble from the chat panel."""
        if hasattr(self, "_status_bubble") and self._status_bubble:
            self._status_bubble.stop_animation()
            self._status_bubble.setParent(None)
            self._status_bubble.deleteLater()
            self._status_bubble = None

    def _on_status_update(self, event_type: str, message: str):
        """Forward status events to the StatusBubble widget."""
        if hasattr(self, "_status_bubble") and self._status_bubble:
            self._status_bubble.update_status(event_type, message)
            self._scroll_to_bottom()

    def _on_response(self, text: str):
        self._hide_status_bubble()
        self.chat_history.append({"role": "assistant", "content": text})
        self.chat_panel.add_message(text, "assistant")
        self._scroll_to_bottom()
        self._set_thinking(False)

    def _on_error(self, error: str):
        self._hide_status_bubble()
        self.chat_panel.add_message(f"⚠ Error: {error}", "system")
        self._scroll_to_bottom()
        self._set_thinking(False)

    def _set_thinking(self, thinking: bool):
        self._is_thinking = thinking
        self.send_btn.setEnabled(not thinking)
        self.input_box.setEnabled(not thinking)
        if thinking:
            self.status_lbl.setText("● Procesando...")
            self.status_lbl.setStyleSheet(f"color: {WARN}; font-size: 11px; padding: 2px 8px;")
        else:
            self.status_lbl.setText("● Listo")
            self.status_lbl.setStyleSheet(f"color: {ACCENT2}; font-size: 11px; padding: 2px 8px;")

    def _scroll_to_bottom(self):
        QTimer.singleShot(50, lambda: self.scroll_area.verticalScrollBar().setValue(
            self.scroll_area.verticalScrollBar().maximum()
        ))

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Seleccionar carpeta de proyecto", self.project_path
        )
        if folder:
            self.project_path = folder
            self.path_lbl.setText(self._short_path(folder))
            self.fs_model.setRootPath(folder)
            self.tree.setRootIndex(self.fs_model.index(folder))
            self._build_system_prompt()
            self.chat_panel.add_message(
                f"Proyecto cambiado a: {folder}", "system"
            )
            self._scroll_to_bottom()

    def _clear_chat(self):
        self.chat_history.clear()
        self.chat_panel.clear()
        self.chat_panel.add_message(
            "Historial limpiado. Listo para nuevas órdenes, Lord Regente.", "assistant"
        )
        self._scroll_to_bottom()

    @staticmethod
    def _short_path(path: str) -> str:
        """Acortar path largo para mostrar en label."""
        if len(path) <= 35:
            return path
        parts = path.replace("\\", "/").split("/")
        if len(parts) > 3:
            return f".../{'/'.join(parts[-2:])}"
        return path


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def launch_ui(project_path: str = None, model: str = None):
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = CawlWindow()
    if project_path:
        window.project_path = os.path.abspath(project_path)
        window.path_lbl.setText(window._short_path(window.project_path))
        window.fs_model.setRootPath(window.project_path)
        window.tree.setRootIndex(window.fs_model.index(window.project_path))
        window._build_system_prompt()
    if model:
        window.model = model
        window.model_lbl.setText(f"Modelo: {model}")

    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    launch_ui()
