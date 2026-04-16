"""Helpers for discovering and selecting local Ollama models."""

from __future__ import annotations

import subprocess
from typing import Iterable, Optional


def list_local_ollama_models(timeout: int = 10) -> list[str]:
    """Return installed Ollama model names from `ollama list`."""
    try:
        result = subprocess.run(
            ["ollama", "list"],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=True,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return []

    models: list[str] = []
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    for line in lines[1:]:
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def model_is_available(model: str, available_models: Optional[Iterable[str]] = None) -> bool:
    """Return True when the requested model exists locally."""
    models = list(available_models) if available_models is not None else list_local_ollama_models()
    return model in models


def prompt_for_model_selection(
    available_models: Optional[Iterable[str]] = None,
    default_model: Optional[str] = None,
) -> Optional[str]:
    """
    Ask the user to choose one of the installed models.

    Returns the selected model name, the default model when Enter is pressed,
    or None when no local models are available.
    """
    models = list(available_models) if available_models is not None else list_local_ollama_models()
    if not models:
        return None

    print("\nModelos locales detectados en Ollama:")
    for index, model in enumerate(models, start=1):
        marker = " (actual)" if model == default_model else ""
        print(f"  {index}. {model}{marker}")

    prompt = "Selecciona un modelo por numero"
    if default_model:
        prompt += f" o pulsa Enter para usar '{default_model}'"
    prompt += ": "

    while True:
        choice = input(prompt).strip()
        if not choice:
            return default_model or models[0]
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(models):
                return models[idx]
        if choice in models:
            return choice
        print("Seleccion no valida. Usa el numero de la lista o el nombre exacto del modelo.")
