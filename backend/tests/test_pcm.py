import struct

import pytest

from utils.pcm import strip_wav_header, validate_pcm


def test_validate_pcm_accepts_even_payload() -> None:
    validate_pcm(b"\x00\x01\x02\x03")


@pytest.mark.parametrize("payload", [b"", b"\x00", b"\x00\x01\x02"])
def test_validate_pcm_rejects_invalid_payload(payload: bytes) -> None:
    with pytest.raises(ValueError):
        validate_pcm(payload)


def test_strip_wav_header_finds_data_after_other_chunks() -> None:
    fmt = b"fmt " + struct.pack("<I", 4) + b"meta"
    odd_junk = b"JUNK" + struct.pack("<I", 3) + b"abc" + b"\x00"
    pcm = b"\x01\x02\x03\x04"
    data_chunk = b"data" + struct.pack("<I", len(pcm)) + pcm
    riff_body = b"WAVE" + fmt + odd_junk + data_chunk
    wav = b"RIFF" + struct.pack("<I", len(riff_body)) + riff_body

    assert strip_wav_header(wav) == pcm


def test_strip_wav_header_leaves_raw_pcm_unchanged() -> None:
    pcm = b"\x01\x02\x03\x04"
    assert strip_wav_header(pcm) == pcm
