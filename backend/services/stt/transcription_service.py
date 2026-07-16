"""Contrato e executor do servico de transcricao existente."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from os import PathLike

AudioPath = str | PathLike[str]


class Transcriber(ABC):
    @abstractmethod
    def transcribe(self, audio_path: AudioPath) -> str:
        """Transcreve um arquivo local controlado pela aplicacao."""

        raise NotImplementedError


class TranscriptionService:
    def __init__(self, transcriber: Transcriber, *, max_concurrent: int = 1):
        if max_concurrent <= 0:
            raise ValueError("max_concurrent deve ser maior que zero")
        self._transcriber = transcriber
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def transcribe(self, audio_path: AudioPath) -> str:
        return self._transcriber.transcribe(audio_path)

    async def transcribe_async(
        self, audio_path: AudioPath, *, timeout_seconds: float | None = None
    ) -> str:
        """Executa o transcritor sincrono fora do event loop e com limite."""

        async with self._semaphore:
            operation = asyncio.to_thread(self.transcribe, audio_path)
            if timeout_seconds is None:
                return await operation
            return await asyncio.wait_for(operation, timeout=timeout_seconds)
