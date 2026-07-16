# Design do Backend — ESP32 Audio Player

Documento de design para o backend que serve áudio PCM para a
ESP32 via HTTP streaming. Este documento foi produzido a partir de
sessão de brainstorming e está aprovado para implementação.

## 1. Visão geral

O backend disponibiliza endpoints HTTP consumidos pela ESP32.
Ele opera como um servidor passivo: a ESP32 inicia as conexões
via `GET /audio/stream` e o backend responde com áudio PCM cru.

No futuro, o backend evoluirá para o pipeline completo:

```
Botão push-to-talk → ESP32 grava → envia áudio
  → backend (STT + LLM + TTS) → PCM na fila
  → ESP32 consome via GET /audio/stream → reproduz no alto-falante
```

## 2. Stack

| Decisão | Escolha |
|---|---|
| Linguagem | Python 3.10+ |
| Framework HTTP | FastAPI |
| Servidor ASGI | Uvicorn |
| Testes | pytest + httpx |
| Escopo inicial | Streaming de arquivo PCM estático |
| Estratégia de entrega | Fila em memória com long-poll |

## 3. Estrutura de diretórios

```
backend/
├── requirements.txt
├── main.py                   # entrypoint: uvicorn.run()
├── app.py                    # instância FastAPI, registra rotas
├── routes/
│   └── audio.py              # endpoints: /queue, /stream, /health
├── services/
│   ├── __init__.py
│   └── audio_queue.py        # fila em memória + streaming com backpressure
├── models/
│   └── __init__.py            # alias AudioChunk = bytes
├── tests/
│   ├── __init__.py
│   ├── test_audio_queue.py   # testes unitários da fila
│   └── test_routes.py        # testes de integração HTTP
├── utils/
│   ├── __init__.py
│   └── pcm.py                # validação e conversão de PCM
├── DESIGN.md                 # este arquivo
└── README.md                 # instruções de uso
```

**Princípios de organização:**

- `routes/` — apenas HTTP: recebe request, valida, delega para services, retorna response.
  Zero lógica de negócio.
- `services/` — lógica de negócio pura: fila, streaming, backpressure.
  Zero dependência do FastAPI.
- `models/` — tipos compartilhados simples, sem dependências circulares.
- `utils/` — funções utilitárias puras, sem estado.
- Cada módulo testável isoladamente.

## 4. Modelos (`models/`)

```python
AudioChunk = bytes
```

Mantido mínimo. O domínio atual é simples: bytes entram, bytes saem.
Tipos futuros (`AudioUpload`, `Transcription`, `TtsResponse`) serão
adicionados quando o pipeline de IA for implementado, sem quebrar
nada existente.

## 5. Serviço: AudioQueue (`services/audio_queue.py`)

Coração do backend. Gerencia o áudio pendente e o streaming com
controle de backpressure.

### 5.1 Estado interno

| Campo | Tipo | Descrição |
|---|---|---|
| `_pending` | `Optional[bytes]` | Áudio aguardando transmissão. `None` = vazio. |
| `_ready` | `asyncio.Event` | Sinaliza "há áudio disponível para stream". |
| `_consuming` | `bool` | `True` se há um stream ativo consumindo. |

### 5.2 Interface pública

#### `async enqueue(pcm: bytes) -> None`

Armazena áudio para o próximo stream.

- Se já houver áudio pendente: **substitui** (último áudio vence).
  Isso é intencional para push-to-talk — se o usuário apertar o botão
  duas vezes, só a última resposta importa.
- Seta `_ready`.
- Lança `ValueError` se `pcm` estiver vazio.

#### `async consume(chunk_size: int = 1280) -> AsyncIterator[bytes]`

Generator assíncrono que produz chunks de `chunk_size` bytes.

Fluxo detalhado:

```text
1. Verifica se já há outro stream ativo (_consuming == True)
   → se sim, lança RuntimeError
2. Aguarda _ready ser setado (long-poll, bloqueia até haver áudio)
3. Marca _consuming = True
4. Itera sobre _pending em chunks de chunk_size (padrão 1280 bytes)
5. A cada chunk: await asyncio.sleep(0) → cede controle ao event loop
   → permite que o transporte TCP aplique backpressure
6. Ao terminar todos os chunks sem erro:
   → limpa _pending (seta None)
   → reseta _ready (clear)
   → _consuming = False
7. Se o cliente HTTP desconectar durante o stream:
   → o generator é descartado (exceção GeneratorExit)
   → _pending NÃO é limpo → o mesmo áudio será reentregue na
     próxima conexão
   → _consuming = False
8. Timeout de 30 segundos aguardando _ready:
   → se nenhum áudio for enfileirado em 30s, retorna sem dados
   → a rota HTTP responderá 204 No Content
```

#### `peek() -> bool`

Retorna `True` se há áudio pendente, sem consumi-lo.
Usado pelos endpoints `/health` e `/status`.

### 5.3 Edge cases

| Situação | Comportamento |
|---|---|
| ESP32 conecta com fila vazia | Bloqueia até `_ready` (long-poll). Timeout de 30s → 204. |
| ESP32 desconecta no meio do stream | Áudio preservado. Reconexão reentrega o mesmo. |
| `enqueue()` chamado 2x sem consumir | Substitui: áudio mais recente vence. |
| `enqueue()` com 0 bytes | `ValueError`: "payload vazio". |
| 2 streams simultâneos | 1º prossegue, 2º recebe `RuntimeError`. Rota → 409. |
| Áudio maior que a RAM do servidor | Cada chunk de 1280 bytes é gerado sob demanda. Memória constante. |
| `enqueue()` durante stream ativo | Atualiza `_pending` sem interromper o stream atual. Novo áudio toca na próxima requisição. |

## 6. Utilitário: PCM (`utils/pcm.py`)

### `validate_pcm(data: bytes) -> None`

Lança `ValueError` se:
- `data` estiver vazio
- `len(data)` não for múltiplo de 2 (cada sample s16le = 2 bytes)

### `strip_wav_header(data: bytes) -> bytes`

Se `data` começar com `RIFF`...`WAVE` (header WAV), localiza o chunk
`data` e retorna apenas os samples PCM. Caso contrário, retorna `data`
sem alteração.

Bônus: evita que um upload acidental de `.wav` produza ruído no speaker.

## 7. Rotas HTTP (`routes/audio.py`)

### 7.1 `POST /queue`

Enfileira áudio PCM para reprodução.

```
Request:
  Content-Type: application/octet-stream
  Body: bytes PCM s16le mono 16kHz

Response 202 Accepted:
  {"status": "queued", "bytes": <tamanho em bytes>}

Response 400 Bad Request:
  {"error": "<mensagem>"}
```

**Validações:**
- Body não pode ser vazio.
- Tamanho do body deve ser múltiplo de 2.
- Header WAV é removido automaticamente se detectado.

**Comportamento:** se um stream estiver ativo, o áudio é armazenado
para a próxima requisição (não interrompe o stream atual).

### 7.2 `GET /audio/stream`

A ESP32 consome o stream PCM.

```
Response 200 OK:
  Content-Type: application/octet-stream
  Transfer-Encoding: chunked
  Body: chunks de ~1280 bytes PCM s16le mono 16kHz

Response 204 No Content:
  (fila vazia após 30s de espera)

Response 409 Conflict:
  {"error": "já existe um stream ativo"}
```

**Headers enviados pela ESP32** (`X-Audio-Format`, `X-Audio-Sample-Rate`,
`X-Audio-Channels`) são recebidos e logados, mas não alteram o
comportamento — o backend sempre serve `s16le mono 16kHz`.

**Comportamento long-poll:** a resposta fica aberta até 30 segundos
aguardando áudio. Se chegar antes, transmite imediatamente. Se
expirar, retorna `204` e a ESP32 reconecta (já faz isso com ~1s
de delay).

### 7.3 `GET /health`

Health check para debug e verificação de disponibilidade.

```json
200 OK
{
  "status": "ok",
  "audio_ready": true,
  "stream_active": false
}
```

## 8. Application (`app.py` e `main.py`)

### `app.py`

```python
from fastapi import FastAPI
from routes.audio import router as audio_router
from services.audio_queue import AudioQueue

def create_app() -> FastAPI:
    app = FastAPI(title="ESP32 Audio Backend")
    app.state.audio_queue = AudioQueue()
    app.include_router(audio_router)
    return app
```

A fila é um singleton acessível via `request.app.state.audio_queue`.
Rotas injetam via `Request` do FastAPI.

### `main.py`

```python
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app:create_app", host="0.0.0.0", port=8000, factory=True)
```

## 9. Testes

### 9.1 `tests/test_audio_queue.py` (unitários)

| Teste | Descrição |
|---|---|
| `test_enqueue_and_consume` | Enfileira PCM, consome, verifica chunks produzidos |
| `test_consume_empty_blocks` | Generator aguarda até `enqueue` ser chamado |
| `test_consume_second_client_rejected` | Dois consumers → RuntimeError |
| `test_reenqueue_replaces_pending` | Enfileirar 2x substitui o primeiro |
| `test_consume_disconnect_preserves_audio` | Cliente cai → áudio não é perdido |
| `test_empty_enqueue_rejected` | Body vazio → ValueError |
| `test_consume_respects_chunk_size` | Chunks têm o tamanho configurado |
| `test_consume_large_audio` | Áudio grande é dividido corretamente |
| `test_peek_returns_correct_state` | `peek()` reflete `_pending` |

### 9.2 `tests/test_routes.py` (integração)

| Teste | Descrição |
|---|---|
| `test_queue_valid_pcm` | POST com PCM válido → 202 |
| `test_queue_empty_body` | POST sem body → 400 |
| `test_queue_odd_size_body` | POST com tamanho ímpar → 400 |
| `test_stream_returns_pcm` | Queue + Stream → 200 com corpo PCM |
| `test_stream_no_content_when_empty` | Stream com fila vazia → timeout → 204 |
| `test_health_endpoint` | GET /health → 200 com JSON esperado |
| `test_stream_conflict` | 2 streams simultâneos → 409 |

### 9.3 Como rodar

```bash
cd backend
pip install -r requirements.txt
pytest -v
```

## 10. Plano de evolução (fora do escopo atual)

Quando o firmware ganhar suporte a microfone, o backend será
estendido sem alterar `audio_queue.py` ou as rotas existentes:

```
Futuro: POST /audio/input  (ESP32 envia áudio do microfone)
          │
          v
        services/stt_service.py     (transcrição)
          │
          v
        services/llm_service.py     (processamento IA)
          │
          v
        services/tts_service.py     (síntese de voz)
          │
          v
        FFmpeg pipe → s16le mono 16kHz
          │
          v
        audio_queue.enqueue(pcm)
          │
          v
        GET /audio/stream  →  ESP32 reproduz
```

Novos módulos são adicionados em `services/` sem modificar os
existentes. A rota `audio.py` ganha apenas `POST /audio/input`.

## 11. Checklist de implementação

| # | Tarefa | Arquivo(s) |
|---|---|---|
| 1 | Criar estrutura de diretórios | `backend/`, subpastas |
| 2 | `requirements.txt` | fastapi, uvicorn, pytest, httpx |
| 3 | `models/__init__.py` | alias `AudioChunk` |
| 4 | `utils/__init__.py` | vazio |
| 5 | `utils/pcm.py` | `validate_pcm()`, `strip_wav_header()` |
| 6 | `services/__init__.py` | vazio |
| 7 | `services/audio_queue.py` | `AudioQueue` com `enqueue()`, `consume()`, `peek()` |
| 8 | `routes/audio.py` | endpoints `POST /queue`, `GET /audio/stream`, `GET /health` |
| 9 | `app.py` | `create_app()` com singleton queue |
| 10 | `main.py` | `uvicorn.run()` |
| 11 | `tests/__init__.py` | vazio |
| 12 | `tests/test_audio_queue.py` | 9 testes unitários |
| 13 | `tests/test_routes.py` | 7 testes de integração |
| 14 | `README.md` | instruções de instalação, execução e teste |

## 12. Como testar com a ESP32

```bash
# Terminal 1: sobe o backend
cd backend
pip install -r requirements.txt
python main.py

# Terminal 2: converte um áudio para PCM se necessário
ffmpeg -i resposta.wav -f s16le -acodec pcm_s16le -ac 1 -ar 16000 resposta.pcm

# Terminal 3: envia o áudio para a fila
curl -X POST --data-binary @resposta.pcm http://192.168.1.100:8000/queue

# A ESP32 (configurada para http://192.168.1.100:8000/audio/stream)
# receberá e reproduzirá o áudio automaticamente
```
