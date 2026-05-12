from __future__ import annotations

import json
import os
from typing import Any

import httpx


class OllamaClient:
    def __init__(self, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or os.getenv("OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/")
        self.model = model or os.getenv("OLLAMA_MODEL") or "llama3.2:3b"

    async def chat_json(self, system: str, user: str, schema_hint: str) -> dict[str, Any]:
        """
        Ask Ollama for a JSON object response.
        We keep it robust by extracting the first JSON object from the response.
        """
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": f"{user}\n\nReturn ONLY valid JSON matching this shape:\n{schema_hint}",
                },
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            content = (data.get("message") or {}).get("content") or ""
        return _extract_json_object(content)

    async def chat_text(self, system: str, user: str) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.4},
        }
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(f"{self.base_url}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()
            return (data.get("message") or {}).get("content") or ""


def _extract_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}

    # Fast path: entire content is JSON.
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:  # noqa: BLE001
        pass

    # Robust path: find first {...} block.
    start = text.find("{")
    if start == -1:
        return {}

    depth = 0
    for i in range(start, len(text)):
        ch = text[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start : i + 1]
                try:
                    obj = json.loads(candidate)
                    if isinstance(obj, dict):
                        return obj
                except Exception:  # noqa: BLE001
                    return {}
    return {}

