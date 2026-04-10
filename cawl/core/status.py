"""
Status emitter — canal de eventos en tiempo real para el agente.

Permite que cualquier módulo (executor, planner, tools) emita mensajes
de progreso que la terminal o la UI pueden suscribirse a escuchar.

Uso:
    from cawl.core.status import status

    status.emit("thinking", "Generando plan...")
    status.emit("tool_call", "Llamando read_file → src/main.py")
    status.emit("tool_result", "Leído: 312 líneas")
    status.emit("done", "Respuesta lista")

Suscriptores:
    status.subscribe(callback)   # callback(event_type: str, message: str)
    status.unsubscribe(callback)
"""

from __future__ import annotations
import threading
from typing import Callable

# Tipos de eventos disponibles
EVENT_TYPES = {
    "thinking",      # El agente está razonando / esperando al LLM
    "planning",      # El planner está generando pasos
    "tool_call",     # Se va a ejecutar una herramienta
    "tool_result",   # Resultado de una herramienta (preview)
    "step",          # Inicio de un paso del plan
    "retry",         # Reintento por JSON inválido
    "trim",          # Historial comprimido
    "done",          # Respuesta lista
    "error",         # Error producido
    "agent",         # Mensaje genérico de un agente (multi-agent)
}


class StatusEmitter:
    """
    Thread-safe pub/sub para eventos de progreso del agente.
    Singleton accesible via `from cawl.core.status import status`.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._subscribers: list[Callable[[str, str], None]] = []

    def subscribe(self, callback: Callable[[str, str], None]) -> None:
        """Register a callback(event_type, message) to receive status updates."""
        with self._lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: Callable[[str, str], None]) -> None:
        """Remove a previously registered callback."""
        with self._lock:
            self._subscribers = [s for s in self._subscribers if s != callback]

    def emit(self, event_type: str, message: str) -> None:
        """
        Emit an event to all subscribers.

        Args:
            event_type: One of the EVENT_TYPES keys.
            message: Human-readable status message.
        """
        with self._lock:
            subs = list(self._subscribers)
        for cb in subs:
            try:
                cb(event_type, message)
            except Exception:
                pass  # Never let a bad subscriber crash the agent


# Global singleton
status = StatusEmitter()
