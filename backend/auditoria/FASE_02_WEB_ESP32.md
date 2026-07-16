# Fase 2 — página e servidor web da ESP32

## Identificação

- Data/hora inicial: 2026-07-16T18:32:06-03:00
- Data/hora final: 2026-07-16T19:02:57-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `7e068b1`
- Commit final da implementação: `b3e07fe`
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Servir uma página móvel e receber um arquivo de áudio por vez na ESP32, sem
reter a gravação completa.

## Estado encontrado antes da alteração

O firmware possuía apenas cliente HTTP de saída e player DAC. Não havia
servidor HTTP, HTML embarcado, validação de upload ou controle de concorrência.

## Arquivos criados, alterados e removidos

- Criados: `main/web_page.h`, `main/web_audio_server.c` e `.h`.
- Alterados: `main/http_audio_player.c`, `main/CMakeLists.txt` e
  `main/Kconfig.projbuild`.
- O teste de contrato está em `backend/tests/test_firmware_upload.py`.

## Decisões tomadas e justificativas

- A página usa `XMLHttpRequest` para progresso e envia `File` diretamente.
- O servidor inicia no evento `IP_EVENT_STA_GOT_IP` e permanece separado das
  tarefas de download/reprodução.
- Mutex FreeRTOS com tentativa imediata implementa um upload por vez.
- Tamanho e prefixo MIME são validados antes de iniciar o backend.
- O token não existe no HTML.

## Comandos executados

- `C:\tmp\python312\python.exe -m pytest tests -q --basetemp .pytest_tmp`
- `idf.py -B build-audio-cellular build` com ESP-IDF 5.5.4.

## Testes executados

- Pytest: 45 testes aprovados em 3,34 s.
- Build ESP-IDF: aprovado; binário e ELF gerados.

## Evidências

- Binário: 920.048 bytes (`0xe09f0`).
- Menor partição: `0x100000`; livres `0x1f610` bytes (12%).
- SHA-256 do binário:
  `63f73a0c13593d18eeb5865bf7b80506068f374ae2babb3dd399e6d377a24fb5`.
- Teste confirma ausência de multipart, Base64, `FileReader` e `arrayBuffer`.
- Evidências em `evidencias/fase_02/`.

## Desvios em relação ao plano

Não houve teste físico em Android/iOS nesta execução porque modelos de celular,
SSID/senha e token de bancada não foram fornecidos. O servidor foi validado por
compilação real e contrato estático reproduzível.

## Riscos e pendências

- Abrir a página no IP real da placa e testar navegadores-alvo.
- Medir heap inicial/mínimo/final via serial em hardware.
- A allowlist completa permanece também no backend; o firmware aceita `audio/*`.

## Critérios de conclusão

- [x] Módulos C e página embarcada foram criados.
- [x] Arquivo é enviado diretamente e há progresso no navegador.
- [x] Tamanho e concorrência são validados.
- [x] Firmware compila no ESP-IDF 5.5.4.
- [ ] Celulares-alvo foram validados fisicamente.
- [ ] Heap foi medido na placa.

## Resultado final

A entrega de software da fase está pronta e compilada; aceite físico depende da
configuração e dos aparelhos de bancada.
