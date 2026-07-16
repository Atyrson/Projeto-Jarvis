"""Tipos compartilhados pelo backend de audio."""

AudioChunk = bytes

from .audio_input import AudioJob, AudioJobStatus, AudioJobStore

__all__ = ["AudioChunk", "AudioJob", "AudioJobStatus", "AudioJobStore"]
