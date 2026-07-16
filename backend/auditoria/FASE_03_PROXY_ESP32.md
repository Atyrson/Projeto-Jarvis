# Fase 3 — proxy ESP32 para backend

## Identificação

- Data/hora inicial: 2026-07-16T18:32:06-03:00
- Data/hora final: 2026-07-16T19:02:57-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `7e068b1`
- Commit final da implementação: `b3e07fe`
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Copiar progressivamente o corpo recebido do celular para o backend usando
memória limitada e encaminhar a resposta HTTP ao navegador.

## Estado encontrado antes da alteração

Não havia cliente HTTP de upload, identidade de dispositivo, request ID ou
tratamento coordenado dos dois sockets.

## Arquivos criados, alterados e removidos

- Criados: `main/audio_upload_proxy.c` e `.h`.
- Alterados: CMake, Kconfig e integração do servidor da Fase 2.
- Nenhum arquivo removido.

## Decisões tomadas e justificativas

- Um buffer configurável de 4.096 bytes é alocado uma vez e reutilizado.
- `write_all()` cobre escritas parciais do cliente HTTP.
- A ESP32 injeta token, identidade derivada do MAC e sequência de request ID.
- Resposta e status do backend são enviados em chunks ao celular.
- Progresso é limitado a 256 KiB ou um segundo.
- Falha do celular fecha imediatamente a conexão ao backend.

## Comandos executados

- Mesmos comandos de Pytest e build registrados na Fase 2.

## Testes executados

- Testes de contrato verificam buffer fixo, loop de escrita parcial, headers e
  ausência do token na página.
- Compilação completa com o cliente e servidor HTTP reais do ESP-IDF: sucesso.

## Evidências

- Objetos compilados: `audio_upload_proxy.c.obj` e `web_audio_server.c.obj`.
- Binário final e hash registrados na Fase 2 e em
  `evidencias/fase_03/firmware_build.txt`.
- Eventos implementados: connecting, connected, progress, backend_response,
  completed, aborted e failed.

## Desvios em relação ao plano

SHA-256 ponta a ponta, queda do backend, timeout, desconexão do celular e heap
sob carga ainda exigem a ESP32 configurada na rede. Não foram simulados como
se fossem evidência física.

## Riscos e pendências

- Confirmar comportamento de timeout e desconexão nos navegadores-alvo.
- Capturar série de heap para arquivos pequeno, médio e próximo do limite.
- A URL é HTTP porque a primeira versão assume Wi-Fi controlado.

## Critérios de conclusão

- [x] Buffer fixo e escritas parciais foram implementados.
- [x] Formato, tamanho, request ID, identidade e token são propagados.
- [x] Resposta do backend retorna ao celular.
- [x] Falhas fecham as conexões e possuem códigos públicos estáveis.
- [x] Firmware compila com as dependências reais.
- [ ] Hash ponta a ponta foi medido em hardware.
- [ ] Heap e falhas de rede foram medidos em hardware.

## Resultado final

O proxy está implementado e compilado com memória O(1); a caracterização física
permanece explicitamente pendente.
