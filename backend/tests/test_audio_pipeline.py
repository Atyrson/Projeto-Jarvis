import asyncio
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app import create_app
from config import AudioInputConfig
from models.audio_input import AudioJob, AudioJobStatus, AudioJobStore
from services.audio_pipeline import (
    AudioPipeline,
    AudioTranscriptionStage,
    TranscriptionStageResult,
)
from services.audio_queue import AudioQueue
from services.llm_service import LLMProviderError
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


class FakeStage:
    def __init__(self, root: Path) -> None:
        self.root = root

    async def execute(self, job_id: str) -> TranscriptionStageResult:
        path = self.root / f"{job_id}.normalized.wav"
        path.write_bytes(b"normalized")
        return TranscriptionStageResult("transcricao secreta", path)


class FakeLLM:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.inputs: list[str] = []

    async def generate(self, transcription: str) -> str:
        self.inputs.append(transcription)
        if self.fail:
            raise LLMProviderError("failed")
        return "resposta secreta"


class FakeTTS:
    def __init__(self) -> None:
        self.inputs: list[str] = []

    async def synthesize(self, text: str) -> bytes:
        self.inputs.append(text)
        return b"encoded wav"


class FakeOutputConverter:
    async def convert_to_pcm(self, source: Path, destination: Path) -> bytes:
        assert source.read_bytes() == b"encoded wav"
        pcm = b"\x00\x01\x02\x03"
        destination.write_bytes(pcm)
        return pcm


def full_pipeline(
    root: Path,
    store: AudioJobStore,
    queue: AudioQueue,
    llm: FakeLLM,
    tts: FakeTTS,
) -> AudioPipeline:
    return AudioPipeline(
        AudioInputConfig(input_dir=root, device_token="test"),
        store,
        FakeStage(root),  # type: ignore[arg-type]
        llm,
        tts,
        FakeOutputConverter(),  # type: ignore[arg-type]
        queue,
    )


def test_full_pipeline_enqueues_pcm_and_cleans_temporary_files(
    tmp_path: Path, caplog
) -> None:
    async def scenario() -> None:
        store = AudioJobStore()
        await accepted_job(tmp_path, store)
        queue = AudioQueue(wait_timeout=1)
        llm = FakeLLM()
        tts = FakeTTS()
        pipeline = full_pipeline(tmp_path, store, queue, llm, tts)

        pipeline.submit("a" * 32)
        await pipeline.wait("a" * 32)
        job = await store.get("a" * 32)
        pcm = b"".join([chunk async for chunk in queue.consume()])

        assert job is not None and job.status == AudioJobStatus.QUEUED
        assert pcm == b"\x00\x01\x02\x03"
        assert llm.inputs == ["transcricao secreta"]
        assert tts.inputs == ["resposta secreta"]
        assert not list(tmp_path.iterdir())
        assert "transcricao secreta" not in caplog.text
        assert "resposta secreta" not in caplog.text

    asyncio.run(scenario())


def test_pipeline_failure_never_enqueues_partial_audio(tmp_path: Path) -> None:
    async def scenario() -> None:
        store = AudioJobStore()
        await accepted_job(tmp_path, store)
        queue = AudioQueue(wait_timeout=0)
        pipeline = full_pipeline(
            tmp_path, store, queue, FakeLLM(fail=True), FakeTTS()
        )

        await pipeline.process("a" * 32)
        job = await store.get("a" * 32)
        assert job is not None and job.status == AudioJobStatus.FAILED
        assert job.error == "llm_failed"
        assert not queue.peek()
        assert not list(tmp_path.iterdir())

    asyncio.run(scenario())


def test_lifespan_builds_pipeline_from_injected_services(tmp_path: Path) -> None:
    async def scenario() -> None:
        application = create_app(
            transcription_service=TranscriptionService(FakeTranscriber()),
            audio_input_config=AudioInputConfig(
                input_dir=tmp_path, device_token="test"
            ),
            llm_service=FakeLLM(),
            tts_service=FakeTTS(),
        )
        async with application.router.lifespan_context(application):
            assert isinstance(application.state.audio_pipeline, AudioPipeline)

    asyncio.run(scenario())
