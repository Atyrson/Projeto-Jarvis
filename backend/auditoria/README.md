# Auditoria da implementação de áudio do celular

Este diretório contém um diário por fase e evidências textuais reproduzíveis.
Áudio, modelos, credenciais e transcrições integrais não são versionados.

Os hashes dos commits de implementação são registrados no diário da fase. O
commit que adiciona o próprio diário aparece imediatamente depois no histórico
Git, evitando alterar ou reescrever commits já produzidos.

Fases registradas: baseline STT, upload do backend, página web da ESP32, proxy
ESP32, conversão/STT, LLM/TTS e robustez/observabilidade. Validações que exigem
placa, celulares ou credenciais cobradas permanecem marcadas como pendentes no
diário correspondente.
