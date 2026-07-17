import asyncio
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from config import AudioInputConfig
from models.audio_input import AudioJob, AudioJobStatus, AudioJobStore
from services.audio_cleanup import AudioCleanupService


def config(root: Path) -> AudioInputConfig:
    return AudioInputConfig(
        input_dir=root,
        device_token="test",
        abandoned_file_age_seconds=10,
        job_retention_seconds=20,
        cleanup_interval_seconds=0.05,
    )


def make_old(path: Path, now: datetime, *, seconds: float = 30) -> None:
    timestamp = (now - timedelta(seconds=seconds)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_only_old_recognized_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        old_part = tmp_path / ("a" * 32 + ".part")
        old_upload = tmp_path / ("b" * 32 + ".upload")
        recent_part = tmp_path / ("c" * 32 + ".part")
        unknown = tmp_path / "keep-me.txt"
        for path in (old_part, old_upload, recent_part, unknown):
            path.write_bytes(b"x")
        make_old(old_part, now)
        make_old(old_upload, now)
        make_old(unknown, now)

        removed = await AudioCleanupService(
            config(tmp_path), AudioJobStore()
        ).cleanup_once(now=now)
        assert removed == 2
        assert not old_part.exists()
        assert not old_upload.exists()
        assert recent_part.exists()
        assert unknown.exists()

    asyncio.run(scenario())


def test_cleanup_preserves_active_upload_and_prunes_terminal_job(tmp_path: Path) -> None:
    async def scenario() -> None:
        now = datetime.now(UTC)
        store = AudioJobStore()
        active_id = "d" * 32
        terminal_id = "e" * 32
        active_part = tmp_path / f"{active_id}.part"
        active_part.write_bytes(b"active")
        make_old(active_part, now)
        old = now - timedelta(seconds=30)
        await store.create(
            AudioJob(
                job_id=active_id,
                status=AudioJobStatus.RECEIVING,
                request_id="active",
                device_id="esp32",
                original_filename="active.webm",
                content_type="audio/webm",
                bytes_expected=10,
                created_at=old,
                updated_at=old,
            )
        )
        await store.create(
            AudioJob(
                job_id=terminal_id,
                status=AudioJobStatus.FAILED,
                request_id="failed",
                device_id="esp32",
                original_filename="failed.webm",
                content_type="audio/webm",
                bytes_expected=10,
                error="test",
                created_at=old,
                updated_at=old,
            )
        )

        await AudioCleanupService(config(tmp_path), store).cleanup_once(now=now)
        assert active_part.exists()
        assert await store.get(active_id) is not None
        assert await store.get(terminal_id) is None

    asyncio.run(scenario())


def test_cleanup_background_task_starts_and_stops(tmp_path: Path) -> None:
    async def scenario() -> None:
        service = AudioCleanupService(config(tmp_path), AudioJobStore())
        await service.start()
        assert service._task is not None and not service._task.done()
        await service.shutdown()
        assert service._task is None

    asyncio.run(scenario())
