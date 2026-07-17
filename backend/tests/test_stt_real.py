import asyncio
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pytest

from config import AudioInputConfig
from models.audio_input import AudioJob, AudioJobStatus, AudioJobStore
from services.audio_converter import AudioConverter
from services.audio_pipeline import AudioTranscriptionStage
from services.stt.transcription_service import TranscriptionService
from services.stt.whisper_transcriber import WhisperTranscriber
from tests.test_audio_converter import ffmpeg_tools


@pytest.mark.stt
@pytest.mark.skipif(
    os.getenv("RUN_REAL_STT") != "1", reason="defina RUN_REAL_STT=1 para o modelo real"
)
def test_whisper_base_transcribes_known_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        tools = ffmpeg_tools()
        if tools is None:
            pytest.skip("FFmpeg nao instalado")
        source_fixture = Path(__file__).parents[1] / "uploads" / "arquivo.mp3"
        if not source_fixture.is_file():
            pytest.skip("fixture de audio nao encontrada")
        job_id = "c" * 32
        source = tmp_path / f"{job_id}.upload"
        shutil.copyfile(source_fixture, source)
        now = datetime.now(UTC)
        store = AudioJobStore()
        await store.create(
            AudioJob(
                job_id=job_id,
                status=AudioJobStatus.ACCEPTED,
                request_id="real-stt",
                device_id="test",
                original_filename="known.mp3",
                content_type="audio/mpeg",
                bytes_expected=source.stat().st_size,
                bytes_received=source.stat().st_size,
                file_path=source,
                created_at=now,
                updated_at=now,
            )
        )
        config = AudioInputConfig(
            input_dir=tmp_path,
            device_token="test",
            ffmpeg_bin=tools[0],
            ffprobe_bin=tools[1],
            stt_timeout_seconds=300,
        )
        model_dir = os.getenv("STT_MODEL_DIR", "C:/tmp/whisper-cache")
        stage = AudioTranscriptionStage(
            config,
            store,
            AudioConverter(config),
            TranscriptionService(
                WhisperTranscriber(
                    "base", download_root=model_dir, ffmpeg_bin=tools[0]
                ),
                max_concurrent=1,
            ),
        )
        result = await stage.execute(job_id)
        assert result.text.strip()

    asyncio.run(scenario())
