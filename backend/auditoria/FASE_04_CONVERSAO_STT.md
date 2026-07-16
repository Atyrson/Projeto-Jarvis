# Fase 4 — conversão e integração com o STT existente

## Identificação

- Data/hora inicial: 2026-07-16T19:02:57-03:00
- Data/hora final: 2026-07-16T19:16:10-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `23244a4`
- Commit final da implementação: `3e14e9a`
- Responsável: Codex, preservando o módulo STT do integrante original

## Objetivo

Detectar container/codec/duração, normalizar a entrada para WAV PCM mono 16 kHz
e chamar o `TranscriptionService` existente com caminho controlado.

## Estado encontrado antes da alteração

FFmpeg/ffprobe não estavam instalados. O upload terminava em `.upload`, sem
inspeção real de mídia, limite de duração ou integração produtiva com o STT.

## Arquivos criados, alterados e removidos

- Criados: `services/audio_converter.py`, `services/audio_pipeline.py`,
  `pytest.ini`, `tests/test_audio_converter.py`, `tests/test_audio_pipeline.py`
  e `tests/test_stt_real.py`.
- Alterados: configuração, fábrica da aplicação, adaptador Whisper e `.gitignore`.
- Nenhum arquivo removido.

## Decisões tomadas e justificativas

- FFmpeg e ffprobe são processos sem stdin, com timeout, saída capturada e erros
  públicos estáveis; stderr não é exposto.
- A etapa aceita exclusivamente `<job_id>.upload` dentro do diretório configurado.
- Normalização produz PCM s16le mono 16 kHz em WAV para o STT.
- Modelo real fica sob marcador `stt`; a suíte rápida usa fakes.
- `FFMPEG_BIN`, `FFPROBE_BIN` e `STT_MODEL_DIR` permitem instalação portátil.
- O adaptador adiciona o diretório de FFmpeg ao PATH porque o Whisper chama o
  executável diretamente até mesmo para WAV.

## Comandos executados

- Download e verificação do FFmpeg Essentials 8.1.2.
- `pytest tests -q -m "not stt" --basetemp .pytest_tmp -p no:cacheprovider`
- `pytest tests/test_stt_real.py -q -m stt ... --log-cli-level=INFO`

## Testes executados

- Rápidos: 53 aprovados, 1 separado, 8,54 s.
- Whisper real: 1 aprovado, 1 aviso esperado de FP32 em CPU, 17,53 s.

## Evidências

- FFmpeg/ffprobe: 8.1.2 essentials.
- SHA-256 do ZIP, igual ao publicado:
  `db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec`.
- Matriz validada: WAV PCM 8 kHz gerado → WAV PCM mono 16 kHz; MP3 real de
  7,296 s → WAV PCM mono 16 kHz → Whisper base.
- Modelo pronto: 2.407 ms; probe: 125 ms; conversão: 156 ms; STT: 5.282 ms.
- Texto retornado: 47 caracteres; conteúdo não registrado.
- Fixture MP3: 173.082 bytes, SHA-256
  `0f0ed514b1270f6b74954f1447b2a1d750bb53fb0d28cacad453be9855159dce`.

## Desvios em relação ao plano

A matriz de containers reais de Android/iOS aguarda os aparelhos. Foram
validados WAV gerado e a fixture MP3 existente, sem alegar cobertura de WebM,
M4A e Ogg reais ainda não fornecidos.

## Riscos e pendências

- Medir formatos concretos produzidos pelos celulares-alvo.
- Em CPU, Whisper usa FP32; dimensionar timeout conforme hardware de produção.
- A continuação LLM/TTS e limpeza no sucesso pertencem às Fases 5–6.

## Critérios de conclusão

- [x] FFmpeg/ffprobe possuem timeout e erros estáveis.
- [x] Formato, áudio e duração são detectados.
- [x] Entrada é normalizada para mono 16 kHz.
- [x] STT existente recebe somente caminho controlado.
- [x] Fake e Whisper base real foram aprovados.
- [x] Logs registram somente métricas e contagem de caracteres.
- [ ] Matriz completa dos celulares foi medida fisicamente.

## Resultado final

A conversão e o Whisper base real funcionam de forma reproduzível e fora do
event loop, sem substituir o módulo STT existente nem expor a transcrição.
