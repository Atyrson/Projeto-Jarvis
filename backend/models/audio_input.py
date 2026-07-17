"""Estado e metadados de jobs de audio de entrada."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class AudioJobStatus(str, Enum):
    RECEIVING = "receiving"
    ACCEPTED = "accepted"
    CONVERTING = "converting"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    QUEUED = "queued"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AudioJob:
    job_id: str
    status: AudioJobStatus
    request_id: str
    device_id: str
    original_filename: str
    content_type: str
    bytes_expected: int
    bytes_received: int = 0
    sha256: str | None = None
    file_path: Path | None = None
    error: str | None = None
    created_at: datetime = datetime.min.replace(tzinfo=UTC)
    updated_at: datetime = datetime.min.replace(tzinfo=UTC)

    def public_dict(self) -> dict[str, object]:
        return {
            "job_id": self.job_id,
            "status": self.status.value,
            "stage": self.status.value,
            "error": self.error,
            "bytes": self.bytes_received,
            "sha256": self.sha256,
            "request_id": self.request_id,
            "device_id": self.device_id,
        }


class AudioJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, AudioJob] = {}
        self._lock = asyncio.Lock()

    async def create(self, job: AudioJob) -> None:
        async with self._lock:
            if job.job_id in self._jobs:
                raise ValueError("job_id duplicado")
            self._jobs[job.job_id] = job

    async def get(self, job_id: str) -> AudioJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def update(self, job_id: str, **changes: object) -> AudioJob:
        async with self._lock:
            current = self._jobs[job_id]
            updated = replace(current, updated_at=datetime.now(UTC), **changes)
            self._jobs[job_id] = updated
            if updated.status != current.status:
                logger.info(
                    "event=job.status_changed request_id=%s job_id=%s device_id=%s "
                    "previous=%s status=%s",
                    updated.request_id,
                    job_id,
                    updated.device_id,
                    current.status.value,
                    updated.status.value,
                )
            return updated

    async def snapshot(self) -> tuple[AudioJob, ...]:
        async with self._lock:
            return tuple(self._jobs.values())

    async def prune(self, *, older_than: datetime) -> tuple[str, ...]:
        terminal = {AudioJobStatus.QUEUED, AudioJobStatus.FAILED}
        async with self._lock:
            removed = tuple(
                job_id
                for job_id, job in self._jobs.items()
                if job.status in terminal and job.updated_at < older_than
            )
            for job_id in removed:
                del self._jobs[job_id]
            return removed
