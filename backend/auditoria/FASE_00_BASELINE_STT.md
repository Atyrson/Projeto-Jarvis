# Fase 0 — baseline e integração do STT

## Identificação

- Data/hora inicial: 2026-07-16T18:08:00-03:00
- Data/hora final: 2026-07-16T18:24:27-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `21b6c4a`
- Commit final da implementação: commit imediatamente anterior ao diário
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Preservar o STT existente, alinhar seu contrato com caminhos de arquivos e
retirar o carregamento do Whisper do import da aplicação.

## Estado encontrado antes da alteração

`Transcriber` declarava `bytes`, a implementação recebia caminho, a rota criava
`WhisperTranscriber()` durante o import e a chamada síncrona bloqueava o event
loop. O endpoint `/transcribe` foi preservado como diagnóstico temporário.

## Arquivos criados, alterados e removidos

- Alterados: `app.py`, `routes/audio.py`, `services/stt/transcription_service.py`
  e `services/stt/whisper_transcriber.py`.
- Criado: `tests/test_stt_integration.py`.
- Nenhum arquivo removido.

## Decisões tomadas e justificativas

- A fábrica de aplicação recebe dependências falsas e não carrega STT por
  padrão; o objeto ASGI de produção habilita a carga no lifespan.
- A importação de `whisper` ficou atrás da fábrica para manter coleta de testes
  leve.
- `asyncio.to_thread()` e um semáforo limitam chamadas intensivas.
- Logs registram evento, duração e caracteres, nunca o texto transcrito.

## Comandos executados

- `C:\tmp\python312\python.exe -m pip install -r backend\requirements.txt`
- `C:\tmp\python312\python.exe -m pip check`
- `C:\tmp\python312\python.exe -m pytest tests -q`

## Testes executados

- Comando: `C:\tmp\python312\python.exe -m pytest tests -q`
- Resultado: sucesso, 29 testes.
- Duração Pytest: 1,06 s.

## Evidências

- Python 3.12.4.
- `openai-whisper` 20250625.
- Torch 2.13.0+cpu.
- `pip check`: nenhuma dependência quebrada.
- Saída da suíte em `evidencias/fase_00/pytest.txt`.
- FFmpeg/ffprobe ainda não estavam no `PATH`; instalação e validação pertencem
  à Fase 4.

## Desvios em relação ao plano

O smoke test real do modelo não foi executado nesta fase porque o artefato do
modelo ainda não estava em cache e FFmpeg não estava instalado. A integração
real está reservada para a Fase 4; os testes rápidos usam transcritor falso.

## Riscos e pendências

- Medir carga e transcrição reais após instalar FFmpeg e obter o modelo.
- `/transcribe` ainda aceita um caminho informado pelo cliente por ser apenas
  diagnóstico; o fluxo de produção não utilizará esse endpoint.

## Critérios de conclusão

- [x] Contrato abstrato aceita caminho de arquivo.
- [x] Importar a aplicação não carrega o modelo.
- [x] Serviço é injetável nos testes.
- [x] Transcrição síncrona não bloqueia o event loop.
- [x] Concorrência é limitada.
- [x] Logs não incluem transcrição nem áudio.

## Resultado final

O STT existente pode ser chamado por serviço injetado, fora do event loop e
com teste reproduzível, sem alterar o motor criado pelo outro integrante.
