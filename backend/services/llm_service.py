"""Interface LLM e implementacao HTTP da API Chat Completions da DeepSeek."""

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


class DeepSeekChatLLMService:
    def __init__(
        self,
        config: AudioInputConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not config.llm_api_key:
            raise AIProviderNotConfigured("DEEPSEEK_API_KEY ausente")
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.llm_base_url.rstrip("/") + "/",
            timeout=config.ai_timeout_seconds,
        )

    async def generate(self, transcription: str) -> str:
        if not transcription.strip():
            raise AIProviderError("transcricao vazia")
        try:
            response = await self._client.post(
                "chat/completions",
                headers={"Authorization": f"Bearer {self.config.llm_api_key}"},
                json={
                    "model": self.config.llm_model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Responda em português brasileiro, de forma curta, "
                                "clara e adequada para ser falada por um alto-falante."
                            ),
                        },
                        {"role": "user", "content": transcription},
                    ],
                    "thinking": {"type": "disabled"},
                    "max_tokens": self.config.llm_max_output_tokens,
                    "stream": False,
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
        choices = document.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        choice = choices[0]
        if not isinstance(choice, dict):
            return ""
        message = choice.get("message")
        if not isinstance(message, dict):
            return ""
        content = message.get("content")
        return content.strip() if isinstance(content, str) else ""

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
