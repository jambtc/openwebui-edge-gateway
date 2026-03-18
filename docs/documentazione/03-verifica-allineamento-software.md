# Verifica Allineamento Software / Documentazione

Data verifica: 2026-03-17

## Scope della verifica

Verifica eseguita tra:

- [01-flusso-dati-edge-gateway.md](/var/www/openwebui-edge-gateway/docs/documentazione/01-flusso-dati-edge-gateway.md)
- [02-modifiche-vps-rollout.md](/var/www/openwebui-edge-gateway/docs/documentazione/02-modifiche-vps-rollout.md)
- [00-contesto-iniziale.md](/var/www/openwebui-edge-gateway/docs/00-contesto-iniziale.md)
- [README.md](/var/www/openwebui-edge-gateway/README.md)

E il software/configurazione reale:

- [server.py](/var/www/openwebui-edge-gateway/openclaw_openai_proxy/server.py)
- [config.yaml](/var/www/openwebui-edge-gateway/config.yaml)
- [docker-compose.yml](/var/www/openwebui-edge-gateway/docker-compose.yml)
- [/var/www/open-webui/.env](/var/www/open-webui/.env)
- [/var/www/open-webui/docker-compose.yaml](/var/www/open-webui/docker-compose.yaml)
- [/var/www/openclaw-based-backend/docker-compose.infra.yml](/var/www/openclaw-based-backend/docker-compose.infra.yml)
- [/var/www/openclaw-based-backend/scripts/dev_run.sh](/var/www/openclaw-based-backend/scripts/dev_run.sh)

## Esito sintetico

Esito: documentazione riallineata al software corrente.

Scostamenti trovati e corretti nella documentazione:

1. repo/path gateway ancora riportato in alcuni punti come `openclaw-openai-proxy`
2. documentazione incompleta sul supporto OIDC/Keycloak dietro gateway
3. descrizione non allineata della priorita URL documento (`presigned_get_url` vs `download_url`)
4. assenza del mapping reale `model=main -> openclaw:assistant`
5. assenza esplicita del catch-all edge e del ruolo del WebSocket passthrough

## Matrice di verifica

| Area | Stato reale software | Esito |
| --- | --- | --- |
| Upload Box `/api/v1/files` | Intercettato dal gateway e inoltrato al `be` | OK |
| Stato processing file | `GET /api/v1/files/{id}/process/status` servito dal gateway | OK |
| Correlazione chat/file | Gestita via `/api/v1/chats/new` e `/api/v1/chats/{chat_id}` | OK |
| Inject browser-side | Attivo su `/api/chat/completions` e `/api/v1/chat/completions` | OK |
| Reinject provider-side | Attivo sulla completion reale `/v1/chat/completions` | OK |
| `/v1/completions` | Inoltro al `be` attivo | OK |
| `/v1/responses` | Inoltro al `be` attivo con fallback a chat completions se `404` | OK |
| WebSocket Box | Passthrough attivo su `/ws/socket.io/*` | OK |
| Catch-all edge | Route non intercettate inoltrate a Box | OK |
| OIDC/Keycloak dietro gateway | Funzionante con `Set-Cookie` multipli preservati | OK |
| Forwarded headers | `Host`, `X-Forwarded-*` inoltrati dal gateway | OK |
| Porte gateway | `3001 -> 4010`, `4010 -> 4010` | OK |
| Porte Box locale | `3002 -> 8080` | OK |
| Porte BE infra | Postgres `5432`, MinIO `9000/9001`, Keycloak `8080`, app `8000` | OK |
| Model mapping | `main` esposto a Box, normalizzato a `openclaw:assistant` | OK |
| URL documento finale consumabile da OPC | Non risolto: `be` restituisce host locale `localhost:9000` | APERTO |

## Punto aperto residuo

Il solo scostamento residuo non e tra documento e software, ma tra software gateway e piattaforma downstream:

- il gateway oggi e coerente con il proprio codice e con la documentazione aggiornata
- il `be` continua a restituire `public_url` e `presigned_get_url` su `localhost:9000`
- OPC non puo consumare quegli URL fuori dal network locale del `be`

Conclusione:

- la documentazione ora descrive correttamente il comportamento del gateway
- la chiusura completa del flusso documentale richiede un fix lato `be` / MinIO exposure / URL pubblico effettivo
