# Contesto Iniziale (gateway / boxedai / be / openclaw)

Data aggiornamento: 2026-03-17

## Riferimenti repository

- `gateway`: `/var/www/openwebui-edge-gateway`
- `boxedai` (Open WebUI): `/var/www/open-webui`
- `be`: `/var/www/openclaw-based-backend` (path richiesto nel brief iniziale: `/var/www/openclaw-based-backed`)
- `openclaw` (opc): `https://github.com/openclaw/openclaw`

## Naming condiviso

- `gateway` = edge gateway davanti a Box (container: `opc-proxy`)
- `boxedai` / `box` = Open WebUI (container: `open-webui`)
- `be` = openclaw-based-backend (BFF + RAG documentale)
- `openclaw` / `opc` = runtime agent a valle del backend

## Flusso logico di riferimento

- `boxedai -> gateway -> be -> openclaw` (e ritorno)
- vincolo documentale: upload file deve passare da `gateway -> be`, senza persistenza finale nel dominio Box
- vincolo auth: il dominio Box pubblico deve passare dal gateway anche per il flusso OIDC

## Stato implementazione (validato)

- `POST /api/v1/files` intercettato dal gateway e inoltrato a `be /api/v1/uploads`
- risposta upload BE adattata a shape Box-compatible
- `GET /api/v1/files/{id}/process/status?stream=true` servita dal gateway
- `GET /api/v1/files/{id}/content` servita dal gateway come proxy verso il download `be`
- intercetto chat Box completato su:
  - `POST /api/v1/chats/new`
  - `POST|PUT|PATCH /api/v1/chats/{chat_id}`
  - `POST /api/chat/completions`
  - `POST /api/v1/chat/completions`
- routing OpenAI compatibile attivo verso BE:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/responses` (con fallback su chat/completions se upstream non disponibile)
- edge pass-through attivo per route non intercettate (gateway davanti a Box)
- pass-through WebSocket attivo su `/ws/socket.io/*`
- reinject provider-side completato: il gateway conserva il contesto documento e lo riapplica sulla completion reale emessa da Box verso `/v1/chat/completions`
- OIDC/Keycloak dietro gateway funzionante: il gateway preserva `Set-Cookie` multipli e inoltra gli header forwarded necessari

## Porte e servizi (topologia locale test)

- `opc-proxy` (gateway):
  - `3001 -> 4010` (entrypoint FE/API)
  - `4010 -> 4010` (entrypoint provider OpenAI-compatible)
- `open-webui` (boxedai backend):
  - `3002 -> 8080` (upstream del gateway)
- `mvp-qdrant`:
  - `6333 -> 6333`
- `ollama`:
  - nessuna porta pubblicata nel compose locale Box
  - servizio interno Docker usato da Box su `11434`
- `be` remoto:
  - `https://be-boxedai-contabo.theia-innovation.com` (443)
- `openclaw` runtime (a valle BE):
  - `18789` / `18789/ws` (infrastruttura runtime)
- `postgres` BE infra:
  - `5432 -> 5432`
- `minio` BE infra:
  - `9000 -> 9000` (API/S3)
  - `9001 -> 9001` (console)
- `keycloak` BE infra:
  - `8080 -> 8080`
- `be` applicativo:
  - `8000` esposto dal processo FastAPI avviato con `scripts/dev_run.sh`

Nota: in locale il browser usa `http://localhost:3001` (gateway). Il gateway inoltra a Box su `BOX_BASE_URL` (attualmente `http://host.docker.internal:3002`).

## Modello / agente

Configurazione attuale del gateway:

- model esposto verso Box: `main`
- agent OpenClaw effettivo inoltrato al `be`: `assistant`

Quindi una richiesta Box con `model=main` viene normalizzata dal gateway in:

- `openclaw:assistant`

## Invarianti tecniche

- nessuna regressione UX lato Box su chat/upload
- login OIDC Box preservato dietro gateway
- mapping file conservato nel gateway (`meta.data.be_upload`)
- log applicativi con evidenza upload BE e shape di ritorno Box
- lookup `GET /api/v1/uploads/{upload_id}/links` usato dal gateway prima della completion
- issue residua non nel perimetro gateway:
  - `be` restituisce `public_url` e `presigned_get_url` con host locale MinIO (`localhost:9000`)
  - il gateway oggi usa in priorita `presigned_get_url`, poi `public_url`, poi `download_url`
  - OPC non puo consumare `localhost` / reti interne per policy runtime
