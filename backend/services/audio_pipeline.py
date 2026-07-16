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
from services.audio_queue import AudioQueue
from services.llm_service import AIProviderError, LLMService
from services.stt.transcription_service import TranscriptionService
from services.tts_service import TTSService
from utils.pcm import validate_pcm

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


class AudioPipeline:
    """Orquestra STT, LLM, TTS, conversao PCM e fila de saida."""

    def __init__(
        self,
        config: AudioInputConfig,
        jobs: AudioJobStore,
        transcription_stage: AudioTranscriptionStage,
        llm: LLMService,
        tts: TTSService,
        converter: AudioConverter,
        audio_queue: AudioQueue,
    ) -> None:
        self.config = config
        self.jobs = jobs
        self.transcription_stage = transcription_stage
        self.llm = llm
        self.tts = tts
        self.converter = converter
        self.audio_queue = audio_queue
        self._tasks: dict[str, asyncio.Task[None]] = {}

    def submit(self, job_id: str) -> None:
        current = self._tasks.get(job_id)
        if current is not None and not current.done():
            return
        task = asyncio.create_task(self.process(job_id), name=f"audio-pipeline-{job_id}")
        self._tasks[job_id] = task
        task.add_done_callback(lambda _completed: self._tasks.pop(job_id, None))

    async def wait(self, job_id: str) -> None:
        task = self._tasks.get(job_id)
        if task is not None:
            await asyncio.shield(task)

    async def process(self, job_id: str) -> None:
        original = self.config.input_dir / f"{job_id}.upload"
        normalized = self.config.input_dir / f"{job_id}.normalized.wav"
        tts_path = self.config.input_dir / f"{job_id}.tts.wav"
        pcm_path = self.config.input_dir / f"{job_id}.response.pcm"
        started = time.monotonic()
        try:
            stage = await self.transcription_stage.execute(job_id)
            await self.jobs.update(job_id, status=AudioJobStatus.LLM)
            logger.info("event=llm.started job_id=%s", job_id)
            answer = await asyncio.wait_for(
                self.llm.generate(stage.text), timeout=self.config.ai_timeout_seconds
            )
            logger.info(
                "event=llm.completed job_id=%s characters=%d", job_id, len(answer)
            )

            await self.jobs.update(job_id, status=AudioJobStatus.TTS)
            logger.info("event=tts.started job_id=%s", job_id)
            encoded_audio = await asyncio.wait_for(
                self.tts.synthesize(answer), timeout=self.config.ai_timeout_seconds
            )
            await asyncio.to_thread(tts_path.write_bytes, encoded_audio)
            logger.info(
                "event=tts.completed job_id=%s bytes=%d", job_id, len(encoded_audio)
            )

            pcm = await self.converter.convert_to_pcm(tts_path, pcm_path)
            validate_pcm(pcm)
            await self.audio_queue.enqueue(pcm)
            await self.jobs.update(job_id, status=AudioJobStatus.QUEUED, error=None)
            logger.info(
                "event=audio_queue.enqueued job_id=%s bytes=%d", job_id, len(pcm)
            )
            logger.info(
                "event=pipeline.completed job_id=%s elapsed_ms=%d result=success",
                job_id,
                round((time.monotonic() - started) * 1000),
            )
        except Exception as exc:
            job = await self.jobs.get(job_id)
            if job is not None and job.status != AudioJobStatus.FAILED:
                if isinstance(exc, asyncio.TimeoutError):
                    error_code = "ai_timeout"
                elif isinstance(exc, (AIProviderError, AudioConversionError)):
                    error_code = exc.error_code
                else:
                    error_code = "pipeline_failed"
                await self.jobs.update(
                    job_id, status=AudioJobStatus.FAILED, error=error_code
                )
                logger.error(
                    "event=pipeline.failed job_id=%s error_code=%s result=failed",
                    job_id,
                    error_code,
                )
        finally:
            for path in (original, normalized, tts_path, pcm_path):
                path.unlink(missing_ok=True)

    async def shutdown(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for service in (self.llm, self.tts):
            close = getattr(service, "aclose", None)
            if close is not None:
                await close()
