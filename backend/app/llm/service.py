from __future__ import annotations

import httpx
import logging
from google import genai
from google.genai import types

from app.config import settings


logger = logging.getLogger("fitlife.llm")
MAX_OUTPUT_TOKENS = 1200


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
                        "options": {"num_predict": MAX_OUTPUT_TOKENS},
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                    },
                )
                response.raise_for_status()

                payload = response.json()
                content = (
                    payload
                    .get("message", {})
                    .get("content", "")
                    .strip()
                )

                if not content:
                    raise ValueError("empty Ollama response")

                logger.info(
                    "llm_completed provider=ollama model=%s finish_reason=%s output_chars=%s",
                    settings.llm_model,
                    payload.get("done_reason", "unknown"),
                    len(content),
                )
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
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                ),
            )

            content = (response.text or "").strip()

            if not content:
                raise ValueError("empty Vertex AI response")

            candidate = response.candidates[0] if getattr(response, "candidates", None) else None
            finish_reason = getattr(candidate, "finish_reason", "unknown")
            logger.info(
                "llm_completed provider=vertex model=%s finish_reason=%s output_chars=%s",
                self.model,
                finish_reason,
                len(content),
            )
            return content

        except Exception as exc:
            raise LLMUnavailable(str(exc)) from exc
