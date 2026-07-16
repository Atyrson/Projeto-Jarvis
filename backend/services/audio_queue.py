"""Fila de ultimo valor para streaming de audio PCM."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from models import AudioChunk


class AudioQueue:
    """Mantem o audio mais recente e permite um unico consumidor por vez.

    O payload em transmissao e fotografado no inicio do consumo. Se outro
    payload chegar durante o stream, ele fica pendente para a proxima
    requisicao e nao interfere no audio atual.
    """

    def __init__(self, wait_timeout: float = 30.0) -> None:
        if wait_timeout < 0:
            raise ValueError("wait_timeout nao pode ser negativo")
        self._wait_timeout = wait_timeout
        self._pending: AudioChunk | None = None
        self._ready = asyncio.Event()
        self._consuming = False
        self._revision = 0
        self._state_lock = asyncio.Lock()

    async def enqueue(self, pcm: AudioChunk) -> None:
        """Armazena ``pcm`` para o proximo stream (o ultimo payload vence)."""

        if not pcm:
            raise ValueError("payload vazio")

        async with self._state_lock:
            self._pending = bytes(pcm)
            self._revision += 1
            self._ready.set()

    async def consume(self, chunk_size: int = 1280) -> AsyncIterator[AudioChunk]:
        """Produz o payload pendente em blocos, aguardando-o por ate 30 s.

        A reserva do consumidor ocorre antes do long-poll. Isso elimina a
        corrida em que dois clientes aguardariam uma fila vazia ao mesmo
        tempo e ambos comecariam quando o audio chegasse.
        """

        if chunk_size <= 0:
            raise ValueError("chunk_size deve ser maior que zero")

        acquired = False
        completed = False
        consumed_revision: int | None = None

        try:
            async with self._state_lock:
                if self._consuming:
                    raise RuntimeError("ja existe um stream ativo")
                self._consuming = True
                acquired = True

            try:
                await asyncio.wait_for(self._ready.wait(), self._wait_timeout)
            except asyncio.TimeoutError:
                return

            async with self._state_lock:
                audio = self._pending
                consumed_revision = self._revision

            if audio is None:
                return

            for offset in range(0, len(audio), chunk_size):
                yield audio[offset : offset + chunk_size]
                await asyncio.sleep(0)

            completed = True
        finally:
            if acquired:
                async with self._state_lock:
                    if completed and self._revision == consumed_revision:
                        self._pending = None
                        self._ready.clear()
                    self._consuming = False

    def peek(self) -> bool:
        """Informa se existe audio pendente, sem consumi-lo."""

        return self._pending is not None

    @property
    def stream_active(self) -> bool:
        """Informa se um consumidor esta transmitindo ou em long-poll."""

        return self._consuming
