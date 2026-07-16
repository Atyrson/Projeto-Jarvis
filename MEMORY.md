# Memória de trabalho do projeto

Este arquivo registra informações duráveis para retomar a implementação em
interações futuras. Atualizá-lo sempre que mudar ambiente, arquitetura,
contratos, decisões importantes ou progresso das fases.

## Objetivo atual

Executar `backend/PLANO_IMPLEMENTACAO_AUDIO_CELULAR.md`: o celular grava e
envia o arquivo cru para a ESP32, a ESP32 encaminha progressivamente ao
backend, e o pipeline STT → LLM → TTS devolve PCM s16le mono 16 kHz ao player.

## Git

- Branch de implementação: `feature/audio-celular-esp32`.
- Branch base e commit inicial: `main` em `21b6c4a`.
- Usar commits incrementais por implementação e auditoria de cada fase.
- O plano, os diários e evidências são versionados em `backend/auditoria/`.

### Commits concluídos

- `1451864` — integração do STT com carga no lifespan e execução fora do event loop.
- `7010599` — auditoria da Fase 0 e versionamento do plano.
- `9b384aa` — upload progressivo no backend.
- `7e068b1` — auditoria da Fase 1.
- `8fbfd35` — criação deste arquivo de memória operacional.
- `b3e07fe` — página móvel, servidor web e proxy de upload da ESP32.

## Ambiente local

- Sistema: Windows/PowerShell.
- Python do backend: `C:\tmp\python312\python.exe` (Python 3.12.4).
- Requirements instalados a partir de `backend/requirements.txt`.
- Torch: 2.13.0+cpu; openai-whisper: 20250625.
- `python` não está no `PATH`; usar sempre o caminho absoluto acima.
- FFmpeg/ffprobe ainda não estavam no `PATH` ao concluir a Fase 3.
- ESP-IDF: 5.5.4 em `C:\Espressif\v5.5.4\esp-idf`.
- Perfil IDF: `C:\Espressif\tools\Microsoft.v5.5.4.PowerShell_profile.ps1`.
- O perfil exige PowerShell com `-ExecutionPolicy Bypass` e acesso fora do sandbox,
  pois seu venv referencia o Python 3.13 da Microsoft Store.
- O diretório `build` antigo usa outro Python. Para não apagá-lo, o build desta
  implementação usa `build-audio-cellular`.

## Comandos reproduzíveis

### Testes do backend

Executar dentro de `backend`:

```powershell
& 'C:\tmp\python312\python.exe' -m pytest tests -q --basetemp .pytest_tmp
```

O `--basetemp` precisa ficar dentro do workspace; o temp padrão em `AppData`
é bloqueado pelo sandbox. Remover `.pytest_tmp` após validar, confirmando antes
que o caminho resolvido permanece dentro de `backend`.

### Build do firmware

Ativar o perfil IDF em um PowerShell com bypass e executar:

```powershell
idf.py -B build-audio-cellular build
```

## Progresso funcional

- Fase 0 concluída: STT injetável, modelo carregado uma vez no lifespan,
  `asyncio.to_thread()` e limite de concorrência. `/transcribe` permanece
  diagnóstico temporário.
- Fase 1 concluída: `POST /audio/input`, `GET /audio/input/{job_id}`,
  autenticação por token, allowlist MIME, limite, `.part`, SHA-256 incremental,
  promoção para `.upload`, limpeza e um upload concorrente.
- Após a Fase 1: 41 testes passavam.
- Fases 2–3 concluídas em software: página móvel, servidor HTTP da ESP32 e
  proxy de 4 KiB; build ESP-IDF aprovado com imagem de 920.048 bytes.
- Após as Fases 2–3: 45 testes passavam.

## Contratos e decisões que não devem regredir

- O navegador envia o objeto `File` diretamente; sem multipart, Base64,
  `FileReader` ou `arrayBuffer()`.
- Uma gravação corresponde a uma única requisição celular → ESP32 e uma única
  requisição ESP32 → backend.
- A ESP32 reutiliza buffer fixo; não acumula a gravação em RAM.
- O backend usa `request.stream()`, nunca `request.body()` em `/audio/input`.
- Nome enviado pelo celular é apenas metadado; caminhos são gerados pelo backend.
- O token existe somente entre ESP32 e backend e nunca entra no HTML ou logs.
- Não registrar áudio, token, texto integral de STT, prompt ou resposta integral.
- Saída final do pipeline: PCM s16le, mono, 16 kHz, validado antes de
  `AudioQueue.enqueue()`.
- Preservar compatibilidade de `/queue`, `/audio/stream` e `/health`.

## Pendências de validação física

- Teste real em Android/iOS e captura da página servida pela placa.
- Logs seriais, heap mínimo/inicial/final e desconexão durante upload.
- Reprodução física no alto-falante após o pipeline completo.
- Smoke test real do Whisper `base` após FFmpeg e modelo estarem disponíveis.
