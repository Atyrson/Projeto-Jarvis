import asyncio
import math
import shutil
import struct
import wave
from pathlib import Path

import pytest

from config import AudioInputConfig
from services.audio_converter import (
    AudioConversionError,
    AudioConversionTimeout,
    AudioConverter,
    AudioDurationExceeded,
)


def ffmpeg_tools() -> tuple[str, str] | None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg and ffprobe:
        return ffmpeg, ffprobe
    roots = list(Path("C:/tmp/ffmpeg").glob("*/bin"))
    if roots:
        return str(roots[0] / "ffmpeg.exe"), str(roots[0] / "ffprobe.exe")
    return None


TOOLS = ffmpeg_tools()
pytestmark = pytest.mark.skipif(TOOLS is None, reason="FFmpeg nao instalado")


def make_wav(path: Path, *, duration: float = 0.1, rate: int = 8000) -> None:
    samples = int(duration * rate)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(rate)
        frames = bytearray()
        for index in range(samples):
            sample = round(6000 * math.sin(2 * math.pi * 440 * index / rate))
            frames.extend(struct.pack("<h", sample))
        output.writeframes(frames)


def config(root: Path, *, max_duration: float = 1.0) -> AudioInputConfig:
    assert TOOLS is not None
    return AudioInputConfig(
        input_dir=root,
        device_token="test",
        max_duration_seconds=max_duration,
        ffmpeg_bin=TOOLS[0],
        ffprobe_bin=TOOLS[1],
    )


def test_probe_and_normalize_real_wav(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "source.upload"
        destination = tmp_path / "normalized.wav"
        make_wav(source)
        converter = AudioConverter(config(tmp_path))
        probe = await converter.normalize_input(source, destination)

        assert probe.format_name == "wav"
        assert probe.codec_name == "pcm_s16le"
        assert probe.duration_seconds == pytest.approx(0.1, abs=0.01)
        with wave.open(str(destination), "rb") as normalized:
            assert normalized.getnchannels() == 1
            assert normalized.getsampwidth() == 2
            assert normalized.getframerate() == 16000

    asyncio.run(scenario())


def test_probe_rejects_invalid_file(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "invalid.upload"
        source.write_text("not audio", encoding="utf-8")
        with pytest.raises(AudioConversionError):
            await AudioConverter(config(tmp_path)).probe(source)

    asyncio.run(scenario())


def test_probe_rejects_duration_above_limit(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "long.upload"
        make_wav(source, duration=0.2)
        with pytest.raises(AudioDurationExceeded):
            await AudioConverter(config(tmp_path, max_duration=0.05)).probe(source)

    asyncio.run(scenario())


def test_output_conversion_produces_valid_pcm(tmp_path: Path) -> None:
    async def scenario() -> None:
        source = tmp_path / "tts.wav"
        destination = tmp_path / "response.pcm"
        make_wav(source, rate=24000)
        pcm = await AudioConverter(config(tmp_path)).convert_to_pcm(
            source, destination
        )
        assert pcm == destination.read_bytes()
        assert len(pcm) == 3200
        assert len(pcm) % 2 == 0

    asyncio.run(scenario())


def test_media_process_timeout_is_enforced(tmp_path: Path, monkeypatch) -> None:
    class SlowProcess:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)
            return b"", b""

        def kill(self) -> None:
            self.returncode = -1

        async def wait(self) -> int:
            return -1

    async def fake_subprocess(*args, **kwargs):
        return SlowProcess()

    async def scenario() -> None:
        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_subprocess)
        base = config(tmp_path)
        timeout_config = AudioInputConfig(
            input_dir=tmp_path,
            device_token="test",
            ffmpeg_bin=base.ffmpeg_bin,
            ffprobe_bin=base.ffprobe_bin,
            media_timeout_seconds=0.01,
        )
        with pytest.raises(AudioConversionTimeout):
            await AudioConverter(timeout_config)._run("fake", event="media.test")

    asyncio.run(scenario())
