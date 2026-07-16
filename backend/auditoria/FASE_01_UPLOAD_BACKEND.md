# Fase 1 — recebimento progressivo no backend

## Identificação

- Data/hora inicial: 2026-07-16T18:24:27-03:00
- Data/hora final: 2026-07-16T18:32:06-03:00
- Branch: `feature/audio-celular-esp32`
- Commit inicial: `7010599`
- Commit final da implementação: `9b384aa`
- Responsável: Codex, sob solicitação do proprietário do repositório

## Objetivo

Receber o corpo binário de áudio progressivamente, aplicar autenticação e
limites, calcular SHA-256 incremental e expor o estado do job.

## Estado encontrado antes da alteração

O backend possuía somente `/queue`, `/audio/stream`, `/health` e o diagnóstico
`/transcribe`. Não havia configuração, estado de job ou armazenamento de
entrada.

## Arquivos criados, alterados e removidos

- Criados: `config.py`, `models/audio_input.py`, `routes/audio_input.py`,
  `services/audio_upload.py`, `tests/test_audio_upload.py` e
  `tests/test_audio_input_routes.py`.
- Alterados: `app.py` e `models/__init__.py`.
- Nenhum arquivo removido.

## Decisões tomadas e justificativas

- O arquivo usa nome aleatório UUID e extensão interna; o nome do cliente é
  somente metadado.
- Cada bloco é escrito e liberado para o sistema operacional antes de pedir o
  próximo, comprovando comportamento progressivo.
- `.part` só é promovido para `.upload` após tamanho e hash final.
- A rota valida token com comparação constante, origem, MIME e tamanho, mas não
  escreve arquivos nem executa IA.
- O gancho `PipelineSubmitter` é injetável e será concretizado nas fases 4–5.

## Comandos executados

- `C:\tmp\python312\python.exe -m pytest tests -q --basetemp .pytest_tmp`
- `git diff --check`
- `git show --stat 9b384aa`

## Testes executados

- Comando: `C:\tmp\python312\python.exe -m pytest tests -q --basetemp .pytest_tmp`
- Resultado: sucesso, 41 testes.
- Duração final: 1,45 s.

## Evidências

- Payload fragmentado de teste: 23 bytes.
- SHA-256 original e reconstruído:
  `ea5368915ae4a5529d1188a8bfca5c98f7f2e8e5ce0877cc901a7c282df49d28`.
- O teste lê o `.part` após o primeiro e o segundo fragmentos, antes do final.
- Cancelamento e erros deixam zero arquivos `.part`.
- Respostas cobertas: `202`, `401`, `409`, `413` e `415`.
- Evidências brutas em `evidencias/fase_01/`.

## Desvios em relação ao plano

O teste TCP real do caminho de entrada será adicionado após a existência do
proxy de firmware e do pipeline, para validar o contrato completo em vez de
duplicar a cobertura ASGI desta fase.

## Riscos e pendências

- Arquivos completos permanecem até o pipeline/limpeza das Fases 4–6.
- O repositório de jobs ainda é somente em memória, adequado à primeira versão.
- A validação de container e duração pertence à Fase 4.

## Critérios de conclusão

- [x] Blocos de tamanhos diferentes produzem arquivo idêntico.
- [x] SHA-256 e tamanho conferem.
- [x] Corpo vazio, divergência e limite são rejeitados.
- [x] `.part` é removido em cancelamento e erro.
- [x] Concorrência é limitada e retorna `409`.
- [x] Nome malicioso não influencia o caminho.
- [x] Rotas existentes continuam compatíveis.

## Resultado final

Um upload fragmentado é reconstruído com hash idêntico sem ser acumulado em
memória, e o job aceito pode ser consultado por identificador não previsível.
