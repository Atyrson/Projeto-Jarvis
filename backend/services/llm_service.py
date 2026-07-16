"""Interface LLM e implementacao HTTP da Responses API."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from config import AudioInputConfig

logger = logging.getLogger(__name__)


class AIProviderError(Exception):
    error_code = "ai_provider_failed"


class AIProviderNotConfigured(AIProviderError):
    error_code = "ai_not_configured"


class LLMProviderError(AIProviderError):
    error_code = "llm_failed"


class LLMService(Protocol):
    async def generate(self, transcription: str) -> str: ...


class UnavailableLLMService:
    async def generate(self, transcription: str) -> str:
        raise AIProviderNotConfigured("provedor LLM nao configurado")


class OpenAIResponsesLLMService:
    def __init__(
        self,
        config: AudioInputConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not config.ai_api_key:
            raise AIProviderNotConfigured("OPENAI_API_KEY ausente")
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.ai_base_url.rstrip("/") + "/",
            timeout=config.ai_timeout_seconds,
        )

    async def generate(self, transcription: str) -> str:
        if not transcription.strip():
            raise AIProviderError("transcricao vazia")
        try:
            response = await self._client.post(
                "responses",
                headers={"Authorization": f"Bearer {self.config.ai_api_key}"},
                json={
                    "model": self.config.llm_model,
                    "instructions": (
                        "Responda em português brasileiro, de forma curta, clara e "
                        "adequada para ser falada por um alto-falante."
                    ),
                    "input": transcription,
                    "max_output_tokens": self.config.llm_max_output_tokens,
                },
            )
            response.raise_for_status()
            document = response.json()
            text = self._extract_text(document)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            logger.error("event=llm.failed error_code=llm_provider_failed")
            raise LLMProviderError("falha no provedor LLM") from exc
        if not text:
            raise LLMProviderError("provedor LLM retornou texto vazio")
        return text

    @staticmethod
    def _extract_text(document: dict[str, object]) -> str:
        direct = document.get("output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        pieces: list[str] = []
        output = document.get("output")
        if isinstance(output, list):
            for item in output:
                if not isinstance(item, dict):
                    continue
                content = item.get("content")
                if not isinstance(content, list):
                    continue
                for part in content:
                    if (
                        isinstance(part, dict)
                        and part.get("type") == "output_text"
                        and isinstance(part.get("text"), str)
                    ):
                        pieces.append(part["text"])
        return "".join(pieces).strip()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
