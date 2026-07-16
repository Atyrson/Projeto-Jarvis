"""Entrypoint do servidor de desenvolvimento/producao simples."""

import uvicorn


if __name__ == "__main__":
    uvicorn.run("app:create_app", host="0.0.0.0", port=8000, factory=True)
