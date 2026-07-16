# Fase 6 — Robustez, limpeza e observabilidade

## Identificação

- Data/hora inicial: 2026-07-16T19:27:00-03:00
- Data/hora final: 2026-07-16T19:45:26-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `a569aaf`
- Commit final da implementação: `b94a46e`
- Atualização do provedor LLM: `6557157` e `c3f0f16`
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Manter sucesso, erro, desconexão e encerramento em estado conhecido, remover
temporários abandonados, reter jobs por tempo limitado e produzir logs
correlacionáveis sem conteúdo sensível.

## Entregas

- `AudioCleanupService` periódico, com proteção dos arquivos de jobs ativos.
- Retenção configurável para jobs terminais `queued` e `failed`.
- Cleanup de `.part`, `.upload`, WAV normalizado, WAV de TTS e PCM de resposta.
- Cancelamento controlado dos jobs do pipeline durante shutdown.
- Eventos exigidos para status, cleanup, rate limit e encerramento.
- Testes TCP reais de fragmentação e desconexão.
- Teste de carga sequencial com 25 uploads no limite de concorrência definido.
- Configuração LLM DeepSeek separada da configuração TTS OpenAI.

## Eventos verificados

| Evento | Origem | Dados permitidos |
|---|---|---|
| `job.status_changed` | `AudioJobStore` | ids, status anterior e atual |
| `cleanup.started` | `AudioCleanupService` | nenhum conteúdo do arquivo |
| `cleanup.file_removed` | `AudioCleanupService` | somente tipo/sufixo |
| `cleanup.completed` | `AudioCleanupService` | contagens e tempo |
| `rate_limit.rejected` | rota de upload | ids e código estável |
| `service.shutdown_started` | lifespan/pipeline | componente |
| `service.shutdown_completed` | lifespan/pipeline | componente |

Nenhum desses eventos registra token, áudio, transcrição, prompt, resposta do
LLM ou corpo remoto de erro.

## Testes e resultados

- Suíte rápida final após a migração TTS: 68 aprovados, 1 teste real DeepSeek
  ignorado e 1 teste STT real desmarcado; 16,45 s.
- Dependências: `pip check` sem pacotes quebrados.
- Whisper real: 1 aprovado; texto transcrito não foi registrado.
- Upload TCP fragmentado: 25.100 bytes reconstruídos com SHA-256 idêntico.
- Desconexão TCP: job `failed/upload_failed`; zero `.part` e `.upload` restantes.
- Carga: 25 uploads × 65.536 bytes = 1.638.400 bytes; zero temporários ao final.
- Firmware ESP-IDF 5.5.4: build aprovado; imagem de 920.048 bytes, 12% livre na
  partição de aplicação.

## Tabela de erros públicos

| Situação | HTTP/estado | Resposta pública |
|---|---:|---|
| token do backend ausente | 503 | token não configurado |
| token inválido | 401 | dispositivo não autorizado |
| headers inválidos | 400 | erro estável sem detalhe interno |
| `Content-Length` ausente | 411 | comprimento obrigatório |
| arquivo acima do limite | 413 | arquivo acima do limite |
| MIME fora da allowlist | 415 | tipo não suportado |
| upload concorrente | 409 | já existe upload ativo |
| corpo interrompido | 400 | tamanho recebido diverge |
| falha interna inesperada | 500 | falha interna no upload |
| falha de pipeline | job `failed` | `error_code` estável |

## Segurança e inventário

- Nenhum padrão de chave `sk-*` ou valor real das variáveis de credencial foi
  encontrado nos arquivos rastreados.
- `sdkconfig`, build, `.env`, `.env.local`, WAV, WebM e PCM não são rastreados.
- `backend/uploads/arquivo.mp3` é uma fixture preexistente, adicionada antes
  desta branch pelo commit `111e000`; tamanho 173.082 bytes e SHA-256
  `0F0ED514B1270F6B74954F1447B2A1D750BB53FB0D28CACAD453BE9855159DCE`.
- A chave DeepSeek fornecida durante a interação não foi copiada para o Git,
  arquivo local, evidência ou log.

## Desvios e pendências externas

- O smoke test real DeepSeek está pronto, mas a credencial não estava exportada
  como `DEEPSEEK_API_KEY` no processo; não foi inserida automaticamente em linha
  de comando ou arquivo para evitar exposição adicional.
- TTS real continua pendente de uma chave OpenAI separada.
- Android/iOS, heap serial, falhas Wi-Fi e reprodução no alto-falante exigem a
  placa e os celulares físicos.

## Checklist global

- [x] Upload passa pela ESP32 no contrato e nos testes de firmware/backend.
- [x] Firmware usa buffer fixo e não acumula o arquivo completo.
- [x] Reconstrução TCP preserva tamanho e SHA-256.
- [x] Upload incompleto não inicia o pipeline e remove temporários.
- [x] Whisper existente é reutilizado fora do event loop.
- [x] Limites existem no navegador, firmware e backend.
- [x] Rotas existentes permanecem cobertas por testes.
- [x] Saída final é PCM s16le mono 16 kHz validado.
- [x] Diários e evidências de todas as fases estão versionados.
- [x] Logs possuem correlação e redaction testada.
- [ ] Fluxo validado em Android e iOS físicos.
- [ ] Heap e recuperação após falhas validados na ESP32 física.
- [ ] Reprodução física do PCM capturada em log serial.

## Resultado final

O critério de conclusão de software da Fase 6 foi atendido: sucesso, falhas,
desconexão e shutdown têm estados e limpeza determinísticos, com testes e
evidências reproduzíveis. Os itens físicos e as chamadas cobradas permanecem
explicitamente pendentes de ambiente externo.
