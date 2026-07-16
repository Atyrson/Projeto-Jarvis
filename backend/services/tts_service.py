"""Interface TTS e implementacao HTTP da Speech API."""

from __future__ import annotations

import logging
from typing import Protocol

import httpx

from config import AudioInputConfig
from services.llm_service import AIProviderError, AIProviderNotConfigured

logger = logging.getLogger(__name__)


class TTSProviderError(AIProviderError):
    error_code = "tts_failed"


class TTSService(Protocol):
    async def synthesize(self, text: str) -> bytes: ...


class UnavailableTTSService:
    async def synthesize(self, text: str) -> bytes:
        raise AIProviderNotConfigured("provedor TTS nao configurado")


class OpenAISpeechTTSService:
    def __init__(
        self,
        config: AudioInputConfig,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not config.tts_api_key:
            raise AIProviderNotConfigured("OPENAI_API_KEY ausente")
        self.config = config
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=config.tts_base_url.rstrip("/") + "/",
            timeout=config.ai_timeout_seconds,
        )

    async def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise AIProviderError("texto TTS vazio")
        try:
            response = await self._client.post(
                "audio/speech",
                headers={"Authorization": f"Bearer {self.config.tts_api_key}"},
                json={
                    "model": self.config.tts_model,
                    "voice": self.config.tts_voice,
                    "input": text,
                    "response_format": "wav",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            logger.error("event=tts.failed error_code=tts_provider_failed")
            raise TTSProviderError("falha no provedor TTS") from exc
        if not response.content:
            raise TTSProviderError("provedor TTS retornou audio vazio")
        return response.content

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()
