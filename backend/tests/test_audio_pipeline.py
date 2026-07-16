import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from config import AudioInputConfig
from models.audio_input import AudioJob, AudioJobStatus, AudioJobStore
from services.audio_pipeline import AudioTranscriptionStage
from services.stt.transcription_service import Transcriber, TranscriptionService


class FakeConverter:
    async def normalize_input(self, source: Path, destination: Path):
        assert source.name.endswith(".upload")
        destination.write_bytes(b"normalized audio")
        return object()


class FakeTranscriber(Transcriber):
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.paths: list[Path] = []

    def transcribe(self, audio_path: str | Path) -> str:
        path = Path(audio_path)
        self.paths.append(path)
        if self.fail:
            raise RuntimeError("model failed")
        return "texto confidencial previsivel"


async def accepted_job(root: Path, store: AudioJobStore, job_id: str = "a" * 32):
    path = root / f"{job_id}.upload"
    path.write_bytes(b"uploaded audio")
    now = datetime.now(UTC)
    await store.create(
        AudioJob(
            job_id=job_id,
            status=AudioJobStatus.ACCEPTED,
            request_id="esp32-1",
            device_id="esp32-test",
            original_filename="phone.webm",
            content_type="audio/webm",
            bytes_expected=path.stat().st_size,
            bytes_received=path.stat().st_size,
            file_path=path,
            created_at=now,
            updated_at=now,
        )
    )
    return path


def make_stage(
    root: Path, store: AudioJobStore, transcriber: FakeTranscriber
) -> AudioTranscriptionStage:
    return AudioTranscriptionStage(
        AudioInputConfig(input_dir=root, device_token="test"),
        store,
        FakeConverter(),  # type: ignore[arg-type]
        TranscriptionService(transcriber),
    )


def test_stage_uses_only_controlled_normalized_path(tmp_path: Path, caplog) -> None:
    async def scenario() -> None:
        store = AudioJobStore()
        await accepted_job(tmp_path, store)
        transcriber = FakeTranscriber()
        result = await make_stage(tmp_path, store, transcriber).execute("a" * 32)
        job = await store.get("a" * 32)

        assert result.text == "texto confidencial previsivel"
        assert result.normalized_path == tmp_path / ("a" * 32 + ".normalized.wav")
        assert transcriber.paths == [result.normalized_path]
        assert job is not None and job.status == AudioJobStatus.STT
        assert result.text not in caplog.text

    asyncio.run(scenario())


def test_stage_rejects_path_not_created_by_upload_service(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = AudioJobStore()
        outside = tmp_path / "client-controlled.wav"
        outside.write_bytes(b"do not delete")
        now = datetime.now(UTC)
        job_id = "b" * 32
        await store.create(
            AudioJob(
                job_id=job_id,
                status=AudioJobStatus.ACCEPTED,
                request_id="esp32-2",
                device_id="esp32-test",
                original_filename="evil.wav",
                content_type="audio/wav",
                bytes_expected=13,
                file_path=outside,
                created_at=now,
                updated_at=now,
            )
        )
        with pytest.raises(Exception, match="controlado"):
            await make_stage(tmp_path, store, FakeTranscriber()).execute(job_id)
        failed = await store.get(job_id)
        assert failed is not None and failed.error == "media_invalid"
        assert outside.exists()

    asyncio.run(scenario())


def test_stt_failure_marks_job_and_cleans_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = AudioJobStore()
        source = await accepted_job(tmp_path, store)
        with pytest.raises(RuntimeError, match="model failed"):
            await make_stage(tmp_path, store, FakeTranscriber(fail=True)).execute(
                "a" * 32
            )
        failed = await store.get("a" * 32)
        assert failed is not None
        assert failed.status == AudioJobStatus.FAILED
        assert failed.error == "stt_failed"
        assert not source.exists()
        assert not list(tmp_path.glob("*.normalized.wav"))

    asyncio.run(scenario())
