# Backend de audio para ESP32

Servidor FastAPI que recebe PCM s16le mono a 16 kHz e o entrega para o
firmware por HTTP chunked. A fila guarda apenas o audio mais recente.

## Requisitos e instalacao

- Python 3.10 ou superior
- ESP32 e computador na mesma rede para o teste em hardware

```powershell
cd backend
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Executar

```powershell
python main.py
```

O servidor escuta em `0.0.0.0:8000`. Configure o firmware com
`http://IP_DO_COMPUTADOR:8000/audio/stream`. Se necessario, autorize a porta
TCP 8000 no firewall local.

Para enfileirar PCM cru:

```powershell
curl.exe -X POST --data-binary "@resposta.pcm" http://localhost:8000/queue
```

Uploads WAV tambem sao aceitos; o backend extrai automaticamente o chunk PCM
`data`. O arquivo deve conter amostras s16le mono a 16 kHz.

## Endpoints

- `POST /queue`: recebe PCM ou WAV e responde `202`.
- `GET /audio/stream`: aguarda audio por ate 30 s e transmite PCM; sem audio,
  responde `204`; um segundo consumidor simultaneo recebe `409`.
- `GET /health`: informa disponibilidade, fila e stream ativo.

## Testes

```powershell
pytest -v
```

A suite inclui teste unitario da fila, integracao ASGI e um teste TCP real com
Uvicorn que reproduz os headers e o tamanho de leitura de 2048 bytes usados em
`main/http_audio_player.c`. Ela tambem confere que o timeout HTTP do firmware e
maior que o long-poll de 30 segundos do backend.

## Proximos passos: audio do microfone

O backend atual implementa somente o caminho de reproducao:

```text
POST /queue -> AudioQueue -> GET /audio/stream -> alto-falante da ESP32
```

O `POST /queue` recebe audio que sera reproduzido. Ele nao deve ser usado para
o audio capturado pelo microfone, pois os dois fluxos terao ciclos de vida,
validacoes e tratamento de erros diferentes.

O proximo fluxo planejado e:

```text
botao push-to-talk
  -> ESP32 captura PCM do microfone
  -> POST /audio/input
  -> STT (transcricao)
  -> LLM (gera a resposta)
  -> TTS (sintetiza PCM s16le mono 16 kHz)
  -> AudioQueue
  -> GET /audio/stream
  -> alto-falante da ESP32
```

### Etapas de implementacao

1. Adicionar ao firmware a captura do microfone e o controle push-to-talk.
   A captura deve produzir PCM em um formato conhecido e enviar os metadados de
   sample rate, canais e formato junto com a requisicao.
2. Criar `POST /audio/input` no backend, separado de `POST /queue`. A primeira
   versao pode receber uma gravacao completa; depois, o endpoint pode evoluir
   para upload em blocos ou processamento incremental.
3. Validar formato, tamanho maximo, duracao, timeout e desconexoes durante o
   upload. O backend deve rejeitar amostras incompletas e nunca manter uploads
   sem limite em memoria.
4. Adicionar servicos independentes para STT, LLM e TTS em `services/`, sem
   acoplar esses provedores as rotas HTTP ou ao `AudioQueue`.
5. Converter a saida do TTS para PCM s16le mono 16 kHz antes de chamar
   `AudioQueue.enqueue()`. Assim, o player existente continua inalterado.
6. Cobrir o novo caminho com testes de upload interrompido, payload invalido,
   limite de tamanho, concorrencia e um teste ponta a ponta
   `microfone -> backend -> alto-falante`.

### Compatibilidade

Os endpoints existentes permanecerao compativeis. Depois que o firmware com
suporte ao microfone for compilado e gravado, cada nova gravacao e resposta
sera processada em tempo de execucao; nao sera necessario recompilar para cada
audio. Uma nova compilacao sera necessaria apenas para alterar codigo ou
configuracoes embutidas no firmware, como Wi-Fi, URL e pinos do microfone.
