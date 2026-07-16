"""Validacao e extracao de audio PCM s16le."""

from __future__ import annotations

import struct


def validate_pcm(data: bytes) -> None:
    """Valida um payload PCM s16le.

    Cada amostra s16le ocupa exatamente dois bytes. A funcao nao tenta
    inferir taxa de amostragem ou numero de canais, pois PCM cru nao carrega
    esses metadados.
    """

    if not data:
        raise ValueError("payload vazio")
    if len(data) % 2:
        raise ValueError("payload PCM deve ter tamanho multiplo de 2 bytes")


def strip_wav_header(data: bytes) -> bytes:
    """Retorna somente o chunk ``data`` de um WAV RIFF, se houver.

    Chunks RIFF podem aparecer em qualquer ordem e sao alinhados em dois
    bytes. Arquivos que nao sao WAV sao devolvidos sem alteracao.
    """

    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        return data

    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        chunk_size = struct.unpack_from("<I", data, offset + 4)[0]
        start = offset + 8
        end = start + chunk_size

        if end > len(data):
            raise ValueError("arquivo WAV truncado")
        if chunk_id == b"data":
            return data[start:end]

        offset = end + (chunk_size % 2)

    raise ValueError("chunk de audio 'data' nao encontrado no WAV")
