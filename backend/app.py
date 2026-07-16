"""Fabrica da aplicacao FastAPI."""

from __future__ import annotations

from fastapi import FastAPI

from routes.audio import router as audio_router
from services.audio_queue import AudioQueue


def create_app(*, audio_queue: AudioQueue | None = None) -> FastAPI:
    app = FastAPI(title="ESP32 Audio Backend")
    app.state.audio_queue = audio_queue or AudioQueue()
    app.include_router(audio_router)
    return app


app = create_app()
