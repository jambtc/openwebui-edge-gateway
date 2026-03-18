# Evoluzione del Progetto

Data aggiornamento: 2026-03-17

## Sintesi

Il progetto nasce come proxy OpenAI-compatible tra BoxedAI e OpenClaw.

Successivamente il requisito documentale ha imposto un cambio di perimetro:

- intercettare `POST /api/v1/files`
- evitare che il file resti nel dominio Box
- correlare upload, chat e completion reale
- mantenere compatibilita piena con frontend Box e con il flusso OIDC

Da qui il passaggio a **OpenWebUI Edge Gateway**.

## Evoluzione sintetica

### Fase iniziale

Flusso iniziale pensato:

- `boxedai -> proxy -> be -> openclaw`

Focus iniziale:

- provider OpenAI-compatible
- session bridge su chat/completions
- coerenza `user_id` / `chat_id`

### Punto di svolta

Il limite emerso e stato questo:

- le Function di OpenWebUI non intercettano direttamente il router HTTP dei file
- l'upload passava internamente a Box su `/api/v1/files`
- il documento non entrava nel dominio applicativo del backend RAG

Conclusione architetturale:

- serviva un layer L7 davanti a Box
- il proxy doveva diventare un edge gateway applicativo

### Fase edge gateway

Il gateway ha quindi assunto questi compiti:

- intercetto upload Box
- adattamento risposta file in shape compatibile Box
- correlazione `chat_id -> file_id/upload_id`
- arricchimento browser-side del payload chat
- reinject provider-side sulla completion reale Box -> `/v1/chat/completions`
- passthrough WebSocket Box
- passthrough HTTP catch-all
- supporto OIDC/Keycloak dietro gateway

## Stato attuale vs storico

Documentazione corrente operativa:

- [../documentazione/01-flusso-dati-edge-gateway.md](/var/www/openwebui-edge-gateway/docs/documentazione/01-flusso-dati-edge-gateway.md)
- [../documentazione/02-modifiche-vps-rollout.md](/var/www/openwebui-edge-gateway/docs/documentazione/02-modifiche-vps-rollout.md)
- [../documentazione/03-verifica-allineamento-software.md](/var/www/openwebui-edge-gateway/docs/documentazione/03-verifica-allineamento-software.md)

Storico decisionale e roadmap incrementale:

- [../bips/README.md](/var/www/openwebui-edge-gateway/docs/bips/README.md)
