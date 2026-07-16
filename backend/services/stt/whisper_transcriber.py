# whiper_transcriber.py

import whisper

from .transcription_service import Transcriber

class WhisperTranscriber(Transcriber):

    def __init__(self):
        self._model = whisper.load_model("base")

    def transcribe(self, audio_path: str) -> str:
        """
        Recebe o caminho de um arquivo de áudio (ex: "audio.wav" ou "audio.mp3")
        e retorna a transcrição textual.
        """
        # 1. Executa a transcrição usando o modelo carregado
        result = self._model.transcribe(audio_path)
        
        # 2. O Whisper retorna um dicionário. O texto completo fica na chave "text"
        return result["text"].strip()