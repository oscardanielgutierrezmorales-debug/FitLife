from __future__ import annotations

import httpx
from google import genai
from google.genai import types

from app.config import settings


class LLMUnavailable(RuntimeError):
    pass


class LocalLLM:
    """Ollama adapter. Agents know this interface, not an Ollama-specific API."""

    async def answer(self, *, system: str, user: str) -> str:
        try:
            async with httpx.AsyncClient(
                timeout=settings.llm_timeout_seconds
            ) as client:
                response = await client.post(
                    f"{settings.llm_base_url.rstrip('/')}/api/chat",
                    json={
                        "model": settings.llm_model,
                        "stream": False,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()

                content = (
                    response.json()
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not content:
                    raise ValueError("empty Ollama response")

                return content

        except (httpx.HTTPError, ValueError) as exc:
            raise LLMUnavailable(str(exc)) from exc


class VertexLLM:
    """Vertex AI adapter. Agents use the same interface as LocalLLM."""

    def __init__(self):
        self.client = genai.Client(
            vertexai=True,
            project="fitlife-510604",
            location="global",
        )
        self.model = "gemini-3.5-flash"

    async def answer(self, *, system: str, user: str) -> str:
        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=user,
                config=types.GenerateContentConfig(
                    system_instruction=system,
                    temperature=0.3,
                    max_output_tokens=800,
                ),
            )

            content = (response.text or "").strip()

            if not content:
                raise ValueError("empty Vertex AI response")

            return content

        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc
        