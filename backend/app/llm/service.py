from __future__ import annotations

import httpx

from app.config import settings


class LLMUnavailable(RuntimeError):
    pass


class LocalLLM:
    """Ollama adapter. Agents know this interface, not an Ollama-specific API."""

    async def answer(self, *, system: str, user: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=settings.llm_timeout_seconds) as client:
                response = await client.post(f"{settings.llm_base_url.rstrip('/')}/api/chat", json={"model": settings.llm_model, "stream": False, "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
                response.raise_for_status()
                content = response.json().get("message", {}).get("content", "").strip()
                if not content:
                    raise ValueError("empty Ollama response")
                return content
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc

