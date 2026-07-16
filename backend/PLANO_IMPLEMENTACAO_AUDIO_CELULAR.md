# Plano de implementação — áudio do celular via ESP32

## 1. Objetivo

Adicionar um caminho de entrada de áudio que cumpra o requisito de vincular o
sensor de entrada à ESP32. O microfone do celular será a origem física da
gravação, mas todo arquivo deverá passar pela ESP32 antes de chegar ao backend.

Fluxo final:

```text
Celular grava o áudio
  -> envia o arquivo para o servidor web da ESP32
  -> ESP32 encaminha o corpo progressivamente para o backend
  -> backend monta e valida o arquivo
  -> STT existente transcreve o arquivo
  -> LLM gera a resposta
  -> TTS sintetiza a resposta
  -> backend converte a saída para PCM s16le mono 16 kHz
  -> AudioQueue.enqueue(pcm)
  -> GET /audio/stream
  -> ESP32 reproduz a resposta no alto-falante
```

A primeira versão será de **gravação seguida de upload progressivo**. Não será
streaming em tempo real enquanto o usuário ainda estiver falando.

## 2. Estado atual do projeto

### 2.1 Backend existente

O backend já possui:

- `POST /queue` para enfileirar áudio de saída;
- `GET /audio/stream` para a ESP32 consumir PCM;
- `GET /health` para diagnóstico;
- `AudioQueue` com long-poll, backpressure e um consumidor por vez;
- validação de PCM e remoção de cabeçalho WAV;
- testes unitários, ASGI e TCP real com o contrato do firmware.

### 2.2 STT já implementado

O STT foi implementado por outro integrante e está localizado em:

```text
backend/services/stt/
├── __init__.py
├── transcription_service.py
├── whisper_transcriber.py
└── faster_whisper_transcriber.py
```

Contrato atual observado:

- `WhisperTranscriber` carrega `whisper.load_model("base")`;
- `WhisperTranscriber.transcribe()` recebe o caminho local de um arquivo;
- `TranscriptionService` delega a transcrição ao transcritor injetado;
- `POST /transcribe`, hoje em `routes/audio.py`, recebe `audio_path` em JSON;
- `faster_whisper_transcriber.py` existe apenas como esqueleto comentado;
- `openai-whisper` e suas dependências já constam em `requirements.txt`.

O STT **não será reimplementado** neste plano. O novo fluxo produzirá um arquivo
local validado e chamará internamente o serviço existente.

### 2.3 Pontos de integração do STT a corrigir

Antes da integração definitiva, serão feitos ajustes pequenos e coordenados,
preservando o trabalho existente:

1. Alinhar a anotação abstrata de `Transcriber.transcribe()`, que atualmente
   declara `bytes`, com a implementação concreta que recebe caminho de arquivo.
2. Evitar `WhisperTranscriber()` no import de `routes/audio.py`, pois isso
   carrega um modelo pesado durante a importação da aplicação e dos testes.
3. Criar o transcritor no ciclo de vida da aplicação e disponibilizá-lo por
   injeção, permitindo um transcritor falso nos testes.
4. Executar a chamada síncrona e intensiva em CPU fora do event loop do
   FastAPI, inicialmente com `asyncio.to_thread()` e concorrência limitada.
5. Não permitir que o fluxo de produção receba do cliente um caminho arbitrário
   do servidor. O pipeline passará ao STT somente caminhos criados pelo serviço
   de upload.
6. Manter `/transcribe` apenas como endpoint diagnóstico temporário ou movê-lo
   para uma rota própria. Sua remoção dependerá de alinhamento com o integrante
   responsável.
7. Não registrar o texto transcrito nos logs de auditoria por padrão.

### 2.4 Firmware existente

O firmware já possui:

- conexão Wi-Fi em modo estação;
- cliente de `GET /audio/stream`;
- conversão PCM s16le para DAC de 8 bits;
- reprodução no GPIO25;
- buffering e reconexão HTTP.

Ainda não existem:

- servidor HTTP na ESP32;
- página web de gravação;
- proxy de upload na ESP32;
- `POST /audio/input` no backend;
- armazenamento temporário progressivo;
- integração do upload com o STT existente;
- serviços LLM e TTS completos.

## 3. Decisões de arquitetura

### 3.1 Uma requisição por gravação

O celular enviará cada gravação em uma única requisição HTTP para a ESP32. A
ESP32 abrirá uma única requisição correspondente para o backend.

```text
POST celular -> ESP32             POST ESP32 -> backend

bloco A --------------------------> bloco A
bloco B --------------------------> bloco B
bloco C --------------------------> bloco C
fim da requisição ----------------> fim da requisição
```

Os limites dos blocos não fazem parte do arquivo. TCP preserva a ordem dos
bytes, mas cada lado pode receber quantidades diferentes em cada leitura.

Não haverá, na primeira versão, um protocolo com `/start`, `/chunk` e
`/finish`. Isso só será necessário para uploads retomáveis ou para blocos
enviados como requisições independentes.

### 3.2 Corpo binário cru

O celular enviará o objeto `File` diretamente no corpo HTTP. Não serão usados:

- `multipart/form-data`;
- Base64;
- JSON contendo áudio;
- `FileReader.readAsArrayBuffer()`;
- `file.arrayBuffer()`.

Essa decisão simplifica o proxy e evita carregar o arquivo completo na memória
do navegador ou da ESP32.

### 3.3 Buffer fixo na ESP32

A ESP32 usará inicialmente um buffer de 4096 bytes:

```text
socket do celular -> buffer de 4 KiB -> socket do backend
```

Depois de encaminhar um bloco, o mesmo buffer será reutilizado. O uso de RAM
não deverá crescer proporcionalmente ao tamanho da gravação.

### 3.4 Arquivo temporário no backend

O backend consumirá `request.stream()` e escreverá os blocos em ordem em
`<job_id>.part`. Ao final, validará tamanho, SHA-256 e formato antes de promover
o arquivo para o estado completo.

`await request.body()` não será usado em `/audio/input`.

### 3.5 STT recebe caminho controlado pelo backend

Depois da montagem e validação:

```text
AudioUploadService
  -> caminho temporário seguro
  -> AudioConverter/ffprobe
  -> TranscriptionService existente
  -> WhisperTranscriber existente
```

O nome informado pelo celular será apenas metadado. O caminho real será gerado
pelo backend e nunca será controlado pelo cliente.

### 3.6 Processamento assíncrono

O backend responderá `202 Accepted` depois de receber e validar o arquivo. STT,
LLM e TTS serão executados posteriormente em um job identificado por `job_id`.

Isso libera a conexão celular -> ESP32 sem esperar o processamento de IA.

## 4. Rastreabilidade e logs de auditoria

Este projeto terá dois tipos complementares de log.

### 4.1 Diário de implementação versionado

Cada fase deverá criar um documento Markdown em:

```text
backend/auditoria/
├── README.md
├── FASE_00_BASELINE_STT.md
├── FASE_01_UPLOAD_BACKEND.md
├── FASE_02_WEB_ESP32.md
├── FASE_03_PROXY_ESP32.md
├── FASE_04_CONVERSAO_STT.md
├── FASE_05_LLM_TTS.md
└── FASE_06_ROBUSTEZ.md
```

Cada diário deverá conter obrigatoriamente:

```markdown
# Fase N — nome

## Identificação
- Data/hora inicial e final
- Branch
- Commit inicial
- Commit final
- Responsável

## Objetivo

## Estado encontrado antes da alteração

## Arquivos criados, alterados e removidos

## Decisões tomadas e justificativas

## Comandos executados

## Testes executados
- comando
- resultado
- quantidade de testes
- duração

## Evidências
- hashes
- trechos de log relevantes
- uso de memória
- respostas HTTP
- resultado de compilação

## Desvios em relação ao plano

## Riscos e pendências

## Critérios de conclusão
- [ ] critério 1
- [ ] critério 2

## Resultado final
```

Os diários serão commitados junto com cada fase. Um critério só poderá ser
marcado como concluído quando houver evidência correspondente.

### 4.2 Evidências brutas versionadas

Saídas importantes serão salvas como `.txt`, pois `*.log` já é ignorado pelo
repositório:

```text
backend/auditoria/evidencias/fase_XX/
├── pytest.txt
├── firmware_build.txt
├── firmware_serial.txt
├── http_contract.txt
├── memory_measurements.txt
└── diff_stat.txt
```

Arquivos volumosos, binários, modelos e gravações não serão versionados. O
diário registrará seu SHA-256 e a forma de reprodução do teste.

### 4.3 Logs de execução

O backend emitirá eventos estruturados, preferencialmente JSON, com os campos:

| Campo | Descrição |
|---|---|
| `timestamp` | Data/hora UTC |
| `level` | `DEBUG`, `INFO`, `WARNING` ou `ERROR` |
| `component` | Serviço ou rota |
| `event` | Nome estável do evento |
| `phase` | Etapa do pipeline |
| `request_id` | Correlação iniciada na ESP32 |
| `job_id` | Identificador criado pelo backend |
| `device_id` | Identificador não secreto da ESP32 |
| `bytes_expected` | Tamanho declarado |
| `bytes_received` | Tamanho acumulado/final |
| `elapsed_ms` | Duração da operação |
| `result` | `success`, `rejected`, `cancelled` ou `failed` |
| `error_code` | Código estável, sem detalhes sensíveis |

Exemplo:

```json
{
  "timestamp": "2026-07-16T20:15:00.000Z",
  "level": "INFO",
  "component": "audio_upload",
  "event": "upload.completed",
  "phase": "receiving",
  "request_id": "esp32-00042",
  "job_id": "01J...",
  "device_id": "esp32-8c94df",
  "bytes_expected": 123456,
  "bytes_received": 123456,
  "elapsed_ms": 840,
  "result": "success",
  "sha256": "..."
}
```

### 4.4 Logs do firmware

O firmware usará `ESP_LOGI`, `ESP_LOGW` e `ESP_LOGE` com pares `chave=valor`:

```text
upload_started request_id=42 bytes_expected=123456 heap_free=148320
upload_progress request_id=42 bytes_forwarded=65536 heap_free=147904
upload_completed request_id=42 status=202 elapsed_ms=840 heap_free=148256
```

Progresso não será registrado a cada bloco de 4 KiB. O intervalo inicial será
a cada 256 KiB ou 1 segundo, evitando impacto excessivo no desempenho.

### 4.5 Dados proibidos nos logs

Nunca registrar:

- senha do Wi-Fi;
- `X-Device-Token`;
- conteúdo binário do áudio;
- texto integral da transcrição;
- prompt ou resposta integral do LLM;
- caminho temporário absoluto em respostas públicas;
- dados pessoais sem necessidade de diagnóstico.

Para auditoria, serão registrados tamanho, hash, duração, contagem de
caracteres e tempos de cada etapa.

## 5. Contratos HTTP

### 5.1 Celular -> ESP32

#### `GET /`

Entrega a página web embarcada.

Responsabilidades:

- abrir o gravador/seletor nativo;
- mostrar nome, tipo e tamanho;
- enviar o `File` diretamente;
- mostrar progresso;
- exibir o resultado retornado pela ESP32.

```html
<input id="audio" type="file" accept="audio/*" capture="user">
```

#### `POST /api/audio/input`

```http
POST /api/audio/input HTTP/1.1
Content-Type: audio/webm
Content-Length: 123456
X-Audio-Filename: gravacao.webm

<bytes do arquivo>
```

Resposta de sucesso:

```http
202 Accepted
Content-Type: application/json

{
  "status": "accepted",
  "job_id": "01J...",
  "bytes": 123456
}
```

Erros:

| Status | Situação |
|---|---|
| `400` | Corpo vazio, tamanho inválido ou formato recusado |
| `409` | Já existe upload ativo na ESP32 |
| `413` | Arquivo acima do limite |
| conexão fechada | Celular interrompeu o upload |
| `502` | Backend indisponível ou rejeitou o upload |
| `504` | Timeout com o backend |

### 5.2 ESP32 -> backend

#### `POST /audio/input`

```http
POST /audio/input HTTP/1.1
Content-Type: audio/webm
Content-Length: 123456
X-Audio-Filename: gravacao.webm
X-Request-Id: esp32-00042
X-Source-Device: esp32
X-Device-Id: esp32-8c94df
X-Device-Token: <segredo>

<bytes encaminhados progressivamente>
```

Resposta:

```json
{
  "status": "accepted",
  "job_id": "01J...",
  "bytes": 123456,
  "sha256": "..."
}
```

#### `GET /audio/input/{job_id}`

```json
{
  "job_id": "01J...",
  "status": "processing",
  "stage": "stt",
  "error": null
}
```

Estados:

```text
receiving -> accepted -> converting -> stt -> llm -> tts -> queued
                                                    \-> failed
```

## 6. Estrutura proposta do backend

```text
backend/
├── app.py
├── main.py
├── config.py
├── routes/
│   ├── audio.py                      # saída e health existentes
│   ├── audio_input.py                # novo upload e status
│   └── transcription.py              # diagnóstico STT, se mantido
├── models/
│   ├── __init__.py
│   └── audio_input.py
├── services/
│   ├── audio_queue.py                # permanece com o contrato atual
│   ├── audio_upload.py               # montagem progressiva
│   ├── audio_pipeline.py             # orquestra as etapas
│   ├── audio_converter.py            # FFmpeg/ffprobe
│   ├── stt/                           # implementação existente
│   │   ├── transcription_service.py
│   │   ├── whisper_transcriber.py
│   │   └── faster_whisper_transcriber.py
│   ├── llm_service.py
│   └── tts_service.py
├── utils/
│   ├── pcm.py
│   └── media.py
├── auditoria/
│   ├── README.md
│   ├── FASE_XX_*.md
│   └── evidencias/
└── tests/
    ├── test_audio_upload.py
    ├── test_audio_input_routes.py
    ├── test_audio_pipeline.py
    ├── test_stt_integration.py
    └── test_cellphone_esp32_flow.py
```

### 6.1 Configuração

Valores iniciais, sobrescrevíveis por ambiente:

| Configuração | Valor sugerido |
|---|---:|
| `AUDIO_INPUT_MAX_BYTES` | 10 MiB |
| `AUDIO_INPUT_MAX_DURATION_SECONDS` | 120 s |
| `AUDIO_INPUT_CHUNK_SIZE` | 64 KiB |
| `AUDIO_INPUT_DIR` | diretório temporário do sistema |
| `AUDIO_INPUT_MAX_CONCURRENT` | 1 |
| `AUDIO_INPUT_DEVICE_TOKEN` | obrigatório fora de testes |
| `STT_MODEL` | `base` |
| `STT_MAX_CONCURRENT` | 1 |
| `STT_TIMEOUT_SECONDS` | valor medido na Fase 0 |

### 6.2 `models/audio_input.py`

```python
class AudioJobStatus(str, Enum):
    RECEIVING = "receiving"
    ACCEPTED = "accepted"
    CONVERTING = "converting"
    STT = "stt"
    LLM = "llm"
    TTS = "tts"
    QUEUED = "queued"
    FAILED = "failed"
```

O modelo guardará metadados e estado, nunca o áudio completo em memória.

### 6.3 `services/audio_upload.py`

Responsabilidades:

- criar `job_id` não previsível;
- criar `<job_id>.part` com abertura exclusiva;
- consumir o iterador assíncrono;
- contar bytes e calcular SHA-256 incrementalmente;
- aplicar o limite durante o recebimento;
- comparar o total com `Content-Length`;
- rejeitar corpo vazio;
- apagar `.part` em cancelamento ou erro;
- promover somente depois da validação;
- ignorar o nome do cliente na construção do caminho.

### 6.4 `routes/audio_input.py`

A rota cuidará apenas de HTTP:

- autenticar o dispositivo;
- validar headers;
- passar `request.stream()` ao serviço;
- mapear exceções para respostas HTTP;
- devolver `202`;
- agendar o pipeline.

Não haverá escrita de arquivo, Whisper, FFmpeg, LLM ou TTS dentro da rota.

### 6.5 `services/audio_converter.py`

FFmpeg/ffprobe será usado para:

- detectar o container real;
- rejeitar arquivos sem áudio;
- medir duração;
- rejeitar duração acima do limite;
- normalizar a entrada para um arquivo aceito pelo Whisper existente;
- converter o TTS para PCM s16le mono 16 kHz.

### 6.6 Integração com `services/stt/`

O pipeline usará a implementação existente:

```text
normalized_audio_path
  -> TranscriptionService.transcribe(path)
  -> WhisperTranscriber.transcribe(path)
  -> texto
```

Regras:

- carregar o modelo uma vez no startup;
- injetar `TranscriptionService` em `app.state` ou no pipeline;
- usar mock/fake nos testes rápidos;
- reservar teste real do modelo para uma marca específica;
- executar fora do event loop;
- limitar concorrência;
- registrar duração e quantidade de caracteres, não o texto;
- preservar a autoria e o histórico dos arquivos do STT.

### 6.7 `services/audio_pipeline.py`

```text
arquivo completo
  -> converter/normalizar entrada
  -> STT existente
  -> LLM
  -> TTS
  -> converter para PCM s16le mono 16 kHz
  -> validate_pcm(pcm)
  -> AudioQueue.enqueue(pcm)
  -> limpar temporários
```

O pipeline usará somente a interface pública de `AudioQueue`.

### 6.8 Alterações em `app.py`

- registrar `audio_input_router`;
- criar serviços no lifespan;
- carregar o Whisper uma vez;
- disponibilizar substitutos nos testes;
- limpar `.part` abandonados;
- finalizar tarefas no shutdown.

## 7. Estrutura proposta do firmware

```text
main/
├── http_audio_player.c
├── web_audio_server.c
├── web_audio_server.h
├── audio_upload_proxy.c
├── audio_upload_proxy.h
├── web_page.h
├── CMakeLists.txt
└── Kconfig.projbuild
```

### 7.1 Servidor web

`web_audio_server.c` deverá:

- iniciar depois do Wi-Fi;
- servir `GET /`;
- receber `POST /api/audio/input`;
- permitir um upload por vez;
- validar tamanho antes de abrir o backend;
- devolver ao celular a resposta do backend;
- encerrar as duas conexões em qualquer erro.

### 7.2 Proxy de upload

`audio_upload_proxy.c` deverá:

- abrir `CONFIG_AUDIO_INPUT_URL`;
- copiar `Content-Type` e tamanho;
- injetar token, `device_id` e `request_id`;
- alternar `httpd_req_recv()` e `esp_http_client_write()`;
- tratar leituras e escritas parciais;
- aplicar timeout;
- abortar o backend se o celular desconectar;
- registrar progresso e heap sem excesso.

```c
remaining = req->content_len;
open_backend_request(remaining);

while (remaining > 0) {
    received = httpd_req_recv(req, buffer, min(sizeof(buffer), remaining));
    if (received <= 0) {
        abort_backend_request();
        return error;
    }

    write_all_to_backend(buffer, received);
    remaining -= received;
}

finish_backend_request();
forward_backend_response_to_phone();
```

### 7.3 Concorrência

```text
tarefa http_stream: GET /audio/stream e reprodução
tarefa do httpd:    upload do celular e proxy para o backend
```

O upload não acessará o stream buffer do DAC. Somente um upload será permitido,
enquanto o player continuará consultando o backend.

### 7.4 Novas configurações

```text
AUDIO_INPUT_URL
AUDIO_UPLOAD_MAX_BYTES
AUDIO_UPLOAD_BUFFER_SIZE
AUDIO_DEVICE_TOKEN
AUDIO_WEB_SERVER_PORT
```

O token será acrescentado pela ESP32 e nunca será exposto no HTML.

### 7.5 Dependências

- adicionar novos arquivos a `SRCS`;
- adicionar `esp_http_server` a `PRIV_REQUIRES`;
- manter `esp_http_client` para upload e reprodução.

## 8. Estratégia de erros

### Celular desconecta

- ESP32 detecta falha em `httpd_req_recv()`;
- fecha a requisição ao backend;
- backend remove `.part`;
- evento `upload.cancelled` é registrado.

### Backend indisponível

- ESP32 responde `502`;
- não armazena o restante em RAM;
- registra endereço sem credenciais, erro e duração.

### Upload incompleto

- backend compara total e `Content-Length`;
- arquivo é descartado;
- pipeline e STT não são iniciados.

### Formato inválido

- job muda para `failed` na etapa `converting`;
- STT não é chamado;
- arquivo é removido segundo a política.

### STT falha

- capturar timeout, falta do FFmpeg, erro do modelo e arquivo incompatível;
- job muda para `failed` com código estável;
- log registra modelo e duração, sem transcrição;
- player permanece operacional.

### LLM ou TTS falha

- job registra a etapa;
- nenhum payload parcial é enfileirado;
- temporários são limpos;
- `/audio/stream` continua disponível.

## 9. Plano de testes

### 9.1 Upload do backend

- blocos de tamanhos diferentes produzem arquivo idêntico;
- SHA-256 e tamanho conferem;
- corpo vazio é rejeitado;
- limite é aplicado durante o stream;
- `Content-Length` divergente é detectado;
- `.part` é removido após cancelamento;
- concorrência é limitada;
- nomes maliciosos não afetam caminhos.

### 9.2 Rotas HTTP

- upload fragmentado retorna `202`;
- token incorreto retorna `401`;
- MIME recusado retorna `415`;
- limite retorna `413`;
- status pode ser consultado;
- upload não quebra rotas atuais;
- pipeline falso enfileira PCM.

### 9.3 STT existente

Testes rápidos:

- pipeline chama `TranscriptionService` com caminho controlado;
- fake transcriber retorna texto previsível;
- exceção vira job `failed`;
- chamada não bloqueia o event loop;
- concorrência respeita o limite.

Teste real separado, por exemplo `@pytest.mark.stt`:

- usa arquivo conhecido;
- confirma que o Whisper `base` carrega;
- confirma transcrição não vazia;
- mede tempo e consumo aproximado;
- salva evidência sem transcrever conteúdo sensível no log.

### 9.4 TCP real

- Uvicorn em socket real;
- corpo deliberadamente fragmentado;
- headers da ESP32;
- SHA-256 original e reconstruído iguais;
- interrupção no meio limpa `.part`;
- resposta do pipeline sai em `/audio/stream`.

### 9.5 Firmware

- página abre pelo IP da ESP32;
- Android e iOS definidos pelo projeto conseguem gravar;
- arquivo pequeno chega intacto;
- arquivo próximo do limite não reinicia a placa;
- acima do limite retorna `413`;
- backend desligado retorna `502`;
- perda de Wi-Fi não trava o upload;
- segundo upload retorna `409`;
- heap retorna ao patamar esperado;
- reprodução funciona após sucesso e falha.

### 9.6 Ponta a ponta

```text
celular grava frase
  -> backend confirma hash
  -> STT existente transcreve
  -> LLM gera resposta
  -> TTS gera áudio
  -> AudioQueue recebe PCM
  -> ESP32 reproduz
```

## 10. Fases de implementação e auditoria

### Fase 0 — Baseline e caracterização do STT existente

Entregas:

- documentar contrato atual do STT;
- executar smoke test controlado com `WhisperTranscriber`;
- medir tempo de carregamento e transcrição;
- alinhar tipo da interface sem alterar o comportamento;
- remover carregamento do modelo no import da rota;
- criar injeção para testes;
- preservar `/transcribe` até decisão conjunta.

Eventos de execução exigidos:

```text
stt.model_loading
stt.model_ready
stt.started
stt.completed
stt.failed
```

Evidências de auditoria:

- `FASE_00_BASELINE_STT.md`;
- versões de Python, Whisper, Torch e FFmpeg;
- tempos de carregamento e transcrição;
- resultado do teste real e dos testes com fake;
- diff limitado aos pontos de integração;
- confirmação de que texto e áudio não aparecem nos logs.

Critério de conclusão: o STT existente pode ser chamado por serviço injetado,
fora do event loop e com teste reproduzível.

### Fase 1 — Recebimento progressivo no backend

Entregas:

- configuração e modelos;
- `AudioUploadService`;
- `POST /audio/input`;
- arquivo temporário, tamanho e SHA-256;
- testes unitários e ASGI;
- pipeline falso.

Eventos exigidos:

```text
upload.request_received
upload.accepted
upload.progress
upload.completed
upload.rejected
upload.cancelled
upload.failed
```

Evidências:

- `FASE_01_UPLOAD_BACKEND.md`;
- pytest completo;
- teste de memória ou evidência de escrita antes do último bloco;
- hashes original e reconstruído;
- limpeza comprovada após interrupção;
- respostas `202`, `401`, `409`, `413` e `415`.

Critério de conclusão: arquivo fragmentado é reconstruído com hash idêntico sem
ser carregado inteiro em RAM.

### Fase 2 — Página e servidor web da ESP32

Entregas:

- módulos C separados;
- HTML/CSS/JS embarcados;
- seleção/gravação no celular;
- recebimento local;
- validação de tamanho e concorrência;
- diagnóstico sem proxy.

Eventos exigidos:

```text
web_server.started
web_page.served
phone_upload.accepted
phone_upload.progress
phone_upload.completed
phone_upload.rejected
```

Evidências:

- `FASE_02_WEB_ESP32.md`;
- compilação completa do firmware;
- log serial de boot e servidor iniciado;
- modelos/versões de celulares e navegadores testados;
- tamanho recebido em cada aparelho;
- heap mínimo, inicial e final;
- captura de resposta HTTP, sem incluir áudio.

Critério de conclusão: celulares-alvo produzem uma gravação e a ESP32 recebe o
tamanho esperado sem reiniciar ou reter o arquivo completo.

### Fase 3 — Proxy ESP32 -> backend

Entregas:

- cópia com buffer fixo;
- propagação de formato e tamanho;
- `request_id`, identidade e token;
- resposta do backend encaminhada ao celular;
- tratamento de falhas nos dois sockets.

Eventos exigidos:

```text
proxy.backend_connecting
proxy.backend_connected
proxy.progress
proxy.backend_response
proxy.completed
proxy.aborted
proxy.failed
```

Evidências:

- `FASE_03_PROXY_ESP32.md`;
- SHA-256 do arquivo original e do backend;
- séries de heap durante arquivos de tamanhos diferentes;
- teste de celular desconectado;
- teste de backend desligado;
- teste de timeout;
- firmware build e serial completos.

Critério de conclusão: backend recebe arquivo idêntico e o heap da ESP32 fica
dentro da margem documentada.

### Fase 4 — Conversão e integração com o STT existente

Entregas:

- FFmpeg/ffprobe com timeout;
- detecção de formato e duração;
- normalização para formato aceito pelo Whisper;
- chamada ao `TranscriptionService` existente;
- estados de job até `stt`;
- testes com fake e teste real marcado.

Esta fase **integra**, mas não substitui, o STT do outro integrante.

Eventos exigidos:

```text
media.probe_started
media.probe_completed
media.conversion_started
media.conversion_completed
media.conversion_failed
stt.started
stt.completed
stt.failed
```

Evidências:

- `FASE_04_CONVERSAO_STT.md`;
- matriz formato/celular/container/codec;
- duração detectada e duração de conversão;
- teste real do Whisper `base`;
- caracteres retornados e tempo, sem texto integral;
- confirmação de que caminhos vêm apenas do upload service;
- reconhecimento da autoria do módulo STT no diário.

Critério de conclusão: formatos reais dos celulares são normalizados e
transcritos pelo serviço já existente de forma reproduzível.

### Fase 5 — LLM, TTS e retorno ao player

Entregas:

- interfaces e implementações LLM/TTS;
- configuração segura dos provedores;
- continuação do pipeline após STT;
- conversão para PCM s16le mono 16 kHz;
- `validate_pcm()` e `AudioQueue.enqueue()`;
- teste ponta a ponta com provedores falsos e real controlado.

Eventos exigidos:

```text
llm.started
llm.completed
llm.failed
tts.started
tts.completed
tts.failed
output.conversion_completed
audio_queue.enqueued
pipeline.completed
pipeline.failed
```

Evidências:

- `FASE_05_LLM_TTS.md`;
- tempos por etapa;
- tamanho e formato da saída;
- validação PCM;
- teste de `/audio/stream` com bytes esperados;
- log serial da reprodução;
- segredos ausentes de logs e commits.

Critério de conclusão: uma transcrição gera resposta PCM reproduzível pela
ESP32 sem intervenção manual.

### Fase 6 — Robustez, limpeza e observabilidade

Entregas:

- status de job;
- limpeza de `.part` abandonados;
- correlação entre `request_id`, `job_id` e `device_id`;
- política de retenção;
- testes de desconexão, timeout e carga;
- documentação final;
- revisão de todos os diários de auditoria.

Eventos exigidos:

```text
job.status_changed
cleanup.started
cleanup.file_removed
cleanup.completed
rate_limit.rejected
service.shutdown_started
service.shutdown_completed
```

Evidências:

- `FASE_06_ROBUSTEZ.md`;
- relatório de testes completo;
- teste de carga dentro do limite definido;
- inventário de temporários antes/depois;
- tabela de erros e respostas;
- auditoria de redaction de logs;
- checklist global assinado no diário.

Critério de conclusão: sucesso e falhas deixam sistema, memória e temporários em
estado conhecido, com evidências suficientes para reproduzir a validação.

## 11. Segurança e limites

- limite aplicado no celular, ESP32 e backend;
- token apenas entre ESP32 e backend;
- um upload por ESP32;
- allowlist de MIME;
- detecção real do formato;
- nomes do cliente nunca viram caminhos;
- temporários removidos;
- timeout em upload, FFmpeg e STT;
- nenhuma credencial no HTML;
- nenhuma credencial, áudio ou transcrição nos logs;
- erros públicos sem detalhes internos.

A primeira versão considera rede Wi-Fi controlada. Uma rede não confiável
exigirá proteção adicional no servidor local.

## 12. Critérios globais de aceite

- toda gravação passa pela ESP32;
- ESP32 não mantém a gravação completa em RAM;
- arquivo reconstruído é idêntico ao original;
- upload incompleto não inicia conversão nem STT;
- STT existente é reutilizado, não duplicado;
- chamadas pesadas não bloqueiam o event loop;
- limites existem nas três camadas;
- rotas atuais continuam compatíveis;
- resposta final é PCM s16le mono 16 kHz;
- ESP32 permanece operacional após sucesso e falha;
- cada fase possui diário e evidências versionadas;
- logs são correlacionáveis e não vazam dados sensíveis;
- fluxo funciona nos celulares definidos pelo projeto.

## 13. Fora do escopo inicial

- transmissão enquanto o usuário ainda fala;
- WebRTC;
- upload retomável;
- múltiplos uploads simultâneos por ESP32;
- armazenamento permanente de gravações;
- novo motor STT;
- substituição do Whisper já implementado;
- interface administrativa completa;
- acesso público ao servidor web da ESP32.

Esses itens poderão evoluir sem alterar o contrato de saída
`AudioQueue -> GET /audio/stream`.
