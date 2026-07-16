"""Etapas do pipeline de audio independentes das rotas HTTP."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path

from config import AudioInputConfig
from models.audio_input import AudioJobStatus, AudioJobStore
from services.audio_converter import AudioConversionError, AudioConverter
from services.stt.transcription_service import TranscriptionService

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TranscriptionStageResult:
    text: str
    normalized_path: Path


class AudioTranscriptionStage:
    def __init__(
        self,
        config: AudioInputConfig,
        jobs: AudioJobStore,
        converter: AudioConverter,
        transcription: TranscriptionService,
    ) -> None:
        self.config = config
        self.jobs = jobs
        self.converter = converter
        self.transcription = transcription

    def _controlled_path(self, job_id: str, path: Path | None) -> Path:
        if path is None:
            raise AudioConversionError("job sem arquivo de entrada")
        expected = (self.config.input_dir / f"{job_id}.upload").resolve()
        if path.resolve() != expected:
            raise AudioConversionError("caminho de entrada nao controlado")
        return expected

    async def execute(self, job_id: str) -> TranscriptionStageResult:
        job = await self.jobs.get(job_id)
        if job is None:
            raise KeyError(job_id)
        source: Path | None = None
        normalized = self.config.input_dir / f"{job_id}.normalized.wav"
        started = time.monotonic()
        try:
            source = self._controlled_path(job_id, job.file_path)
            await self.jobs.update(job_id, status=AudioJobStatus.CONVERTING, error=None)
            await self.converter.normalize_input(source, normalized)
            await self.jobs.update(job_id, status=AudioJobStatus.STT)
            logger.info("event=stt.started job_id=%s", job_id)
            text = await self.transcription.transcribe_async(
                normalized, timeout_seconds=self.config.stt_timeout_seconds
            )
            logger.info(
                "event=stt.completed job_id=%s elapsed_ms=%d characters=%d",
                job_id,
                round((time.monotonic() - started) * 1000),
                len(text),
            )
            return TranscriptionStageResult(text, normalized)
        except asyncio.TimeoutError:
            await self.jobs.update(
                job_id, status=AudioJobStatus.FAILED, error="stt_timeout"
            )
            normalized.unlink(missing_ok=True)
            if source is not None:
                source.unlink(missing_ok=True)
            logger.error("event=stt.failed job_id=%s error_code=stt_timeout", job_id)
            raise
        except Exception as exc:
            error_code = (
                exc.error_code if isinstance(exc, AudioConversionError) else "stt_failed"
            )
            await self.jobs.update(
                job_id, status=AudioJobStatus.FAILED, error=error_code
            )
            normalized.unlink(missing_ok=True)
            if source is not None:
                source.unlink(missing_ok=True)
            logger.error(
                "event=pipeline.failed job_id=%s error_code=%s", job_id, error_code
            )
            raise
