from abc import ABC, abstractmethod

class Transcriber(ABC):

    @abstractmethod
    def transcribe(self, audio: bytes) -> str:
        pass

class TranscriptionService:

    def __init__(self, transcriber: Transcriber):
        self._transcriber = transcriber

    def transcribe(self, audio_path) -> str:
        return self._transcriber.transcribe(audio_path)