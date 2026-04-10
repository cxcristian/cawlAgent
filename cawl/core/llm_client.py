"""
LLM client module.
Handles communication with local Ollama API.
Full-featured client with chat, generate, tool call parsing, and model verification.
"""

import json
import re
import requests
from typing import Optional

from cawl.config.config import get_config


OLLAMA_URL = "http://localhost:11434"
DEFAULT_MODEL = "qwen2.5-coder:7b"


class OllamaClient:
    """Client for interacting with Ollama API."""

    def __init__(self, url: str = OLLAMA_URL, model: str = DEFAULT_MODEL):
        self.url = url.rstrip("/")
        self.model = model
        self._verify_connection()

    def _verify_connection(self) -> None:
        """Verify that Ollama is running and accessible."""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=5)
            response.raise_for_status()
        except requests.exceptions.ConnectionError:
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.url}.\n"
                "Ensure Ollama is running (try: 'ollama serve')."
            )
        except requests.exceptions.Timeout:
            raise TimeoutError(
                f"Connection to Ollama at {self.url} timed out."
            )

    def verify_model(self) -> bool:
        """Check if the specified model is available."""
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=10)
            response.raise_for_status()
            models = [m.get("name", "") for m in response.json().get("models", [])]
            return any(
                self.model == m or self.model.startswith(m.split(":")[0])
                for m in models
            )
        except Exception:
            return False

    def generate(self, prompt: str, temperature: float = 0.1, stream: bool = False) -> str:
        """Send a prompt to Ollama /api/generate and return the response."""
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature,
                "num_predict": 8192,
            },
        }
        try:
            response = requests.post(
                f"{self.url}/api/generate", json=payload, timeout=300
            )
            response.raise_for_status()
            if stream:
                return self._handle_streaming(response)
            return self._handle_non_streaming(response)
        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama request timed out. The model may be loading.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama request failed: {e}")

    def _handle_streaming(self, response: requests.Response) -> str:
        """Handle a streaming response from /api/generate."""
        full_response = ""
        for line in response.iter_lines():
            if line:
                try:
                    data = json.loads(line.decode("utf-8"))
                    if "response" in data:
                        full_response += data["response"]
                    if data.get("done", False):
                        break
                except json.JSONDecodeError:
                    continue
        return full_response.strip()

    def _handle_non_streaming(self, response: requests.Response) -> str:
        """Handle a non-streaming response from /api/generate."""
        try:
            data = response.json()
            return data.get("response", "").strip()
        except json.JSONDecodeError:
            raise RuntimeError("Invalid JSON response from Ollama.")

    def chat(
        self,
        messages: list[dict],
        temperature: float = 0.1,
        json_format: bool = False,
    ) -> str:
        """
        Send a chat conversation to Ollama /api/chat and return response text.

        Args:
            messages: List of message dicts with 'role' and 'content'.
            temperature: Controls randomness.
            json_format: If True, forces Ollama to respond in JSON format.

        Returns:
            The assistant's response text.
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 8192,
            },
        }
        if json_format:
            payload["format"] = "json"

        try:
            response = requests.post(
                f"{self.url}/api/chat", json=payload, timeout=300
            )
            response.raise_for_status()
            data = response.json()
            return data.get("message", {}).get("content", "").strip()
        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama chat request timed out.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama chat request failed: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"Invalid response from Ollama: {e}")

    @staticmethod
    def parse_tool_call_from_text(text: str) -> Optional[dict]:
        """
        Parse a tool call from the model's text response.

        Since Ollama doesn't have native function calling, the model
        outputs JSON in its response text. We detect and parse it.

        Expected format:
            ```json
            {"name": "list_directory", "arguments": {"path": "/some/path"}}
            ```
        or inline:
            {"name": "read_file", "arguments": {"file_path": "/path/to/file"}}

        Returns:
            Dict with 'name' and 'arguments' if found, else None.
        """
        # Strategy 1: JSON inside code blocks
        code_block_match = re.search(r"```(?:json)?\s*\n?([\s\S]*?)\n?\s*```", text)
        if code_block_match:
            json_str = code_block_match.group(1).strip()
            try:
                data = json.loads(json_str)
                if "name" in data and "arguments" in data:
                    return data
            except json.JSONDecodeError:
                pass

        # Strategy 2: Standalone JSON objects with 'name' and 'arguments'
        json_pattern = re.compile(
            r'\{\s*[\'"]name[\'"]\s*:\s*[\'"].*?[\'"]\s*,\s*[\'"]arguments[\'"]\s*:\s*\{[\s\S]*?\}\s*\}'
        )
        match = json_pattern.search(text)
        if match:
            try:
                data = json.loads(match.group(0))
                if "name" in data and "arguments" in data:
                    return data
            except json.JSONDecodeError:
                pass

        return None

    def chat_with_tools(
        self,
        messages: list[dict],
        temperature: float = 0.1,
    ) -> dict:
        """
        Send a chat conversation and parse any tool calls from the response text.

        Returns:
            Dict with 'content' (text) and 'tool_calls' (list of parsed calls).
        """
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": 8192,
            },
        }
        try:
            response = requests.post(
                f"{self.url}/api/chat", json=payload, timeout=300
            )
            response.raise_for_status()
            data = response.json()
            raw_text = data.get("message", {}).get("content", "").strip()

            result = {"content": raw_text, "tool_calls": []}
            tool_call = self.parse_tool_call_from_text(raw_text)
            if tool_call:
                result["tool_calls"].append(tool_call)
            return result

        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama chat_with_tools request timed out.")
        except requests.exceptions.RequestException as e:
            raise RuntimeError(f"Ollama chat_with_tools request failed: {e}")
        except (json.JSONDecodeError, KeyError) as e:
            raise RuntimeError(f"Invalid response from Ollama: {e}")


# ---------------------------------------------------------------------------
# Singleton factory (compatible with new-style modules)
# ---------------------------------------------------------------------------

_client: Optional[OllamaClient] = None


def get_llm_client() -> OllamaClient:
    """Return a singleton OllamaClient using config values."""
    global _client
    if _client is None:
        config = get_config()
        model = config.get("executor.model", DEFAULT_MODEL)
        _client = OllamaClient(model=model)
    return _client
