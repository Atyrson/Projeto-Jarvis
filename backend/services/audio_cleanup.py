"""Limpeza de temporarios abandonados e retencao de jobs."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import AudioInputConfig
from models.audio_input import AudioJobStatus, AudioJobStore

logger = logging.getLogger(__name__)


class AudioCleanupService:
    _recognized_suffixes = (
        ".part",
        ".upload",
        ".normalized.wav",
        ".tts.wav",
        ".response.pcm",
    )

    def __init__(self, config: AudioInputConfig, jobs: AudioJobStore) -> None:
        self.config = config
        self.jobs = jobs
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    async def cleanup_once(self, *, now: datetime | None = None) -> int:
        started = time.monotonic()
        current = now or datetime.now(UTC)
        logger.info("event=cleanup.started")
        self.config.input_dir.mkdir(parents=True, exist_ok=True)
        jobs = await self.jobs.snapshot()
        active_names: set[str] = set()
        for job in jobs:
            if job.status == AudioJobStatus.RECEIVING:
                active_names.add(f"{job.job_id}.part")
            elif job.status not in {AudioJobStatus.QUEUED, AudioJobStatus.FAILED}:
                active_names.update(
                    {
                        f"{job.job_id}.upload",
                        f"{job.job_id}.normalized.wav",
                        f"{job.job_id}.tts.wav",
                        f"{job.job_id}.response.pcm",
                    }
                )

        threshold = current.timestamp() - self.config.abandoned_file_age_seconds
        removed = 0
        for path in self.config.input_dir.iterdir():
            if not path.is_file() or path.name in active_names:
                continue
            if not path.name.endswith(self._recognized_suffixes):
                continue
            try:
                if path.stat().st_mtime >= threshold:
                    continue
                path.unlink()
                removed += 1
                logger.info("event=cleanup.file_removed file_kind=%s", path.suffix)
            except FileNotFoundError:
                continue
            except OSError:
                logger.exception("event=cleanup.file_remove_failed")

        pruned = await self.jobs.prune(
            older_than=current - timedelta(seconds=self.config.job_retention_seconds)
        )
        logger.info(
            "event=cleanup.completed files_removed=%d jobs_removed=%d elapsed_ms=%d",
            removed,
            len(pruned),
            round((time.monotonic() - started) * 1000),
        )
        return removed

    async def start(self) -> None:
        await self.cleanup_once()
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="audio-cleanup")

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.config.cleanup_interval_seconds
                )
            except asyncio.TimeoutError:
                await self.cleanup_once()

    async def shutdown(self) -> None:
        self._stop.set()
        if self._task is not None:
            await self._task
            self._task = None
