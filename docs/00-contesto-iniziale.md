# Contesto Iniziale (proxy / boxedai / be / openclaw)

Data aggiornamento: 2026-03-13

## Riferimenti repository

- `proxy` (gateway): `/var/www/openclaw-openai-proxy`
- `boxedai` (Open WebUI): `/var/www/open-webui`
- `be`: `/var/www/openclaw-based-backend` (path richiesto nel brief: `/var/www/openclaw-based-backed`)
- `openclaw` (opc): `https://github.com/openclaw/openclaw`

## Naming condiviso

- `gateway` = `proxy` evoluto a edge gateway (container: `opc-proxy`)
- `boxedai` / `box` = Open WebUI (container: `open-webui`)
- `be` = openclaw-based-backend (BFF + RAG documentale)
- `openclaw` / `opc` = runtime agent a valle del backend

## Flusso logico di riferimento

- `boxedai -> gateway -> be -> openclaw` (e ritorno)
- vincolo documentale: upload file deve passare da `gateway -> be`, senza persistenza finale nel dominio Box

## Stato implementazione (validato)

- `POST /api/v1/files` intercettato dal gateway e inoltrato a `be /api/v1/uploads`
- risposta upload BE adattata a shape Box-compatible
- `GET /api/v1/files/{id}/process/status?stream=true` servita dal gateway
- intercetto chat Box completato su:
  - `POST /api/v1/chats/new`
  - `POST|PUT|PATCH /api/v1/chats/{chat_id}`
  - `POST /api/chat/completions`
- routing OpenAI compatibile attivo verso BE:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/responses` (con fallback su chat/completions)
- edge pass-through attivo per route non intercettate (gateway davanti a Box)
- reinject provider-side completato: il gateway conserva il contesto documento e lo riapplica sulla completion reale emessa da Box verso `/v1/chat/completions`

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

## Invarianti tecniche

- nessuna regressione UX lato Box su chat/upload
- mapping file conservato nel gateway (`meta.data.be_upload`)
- log applicativi con evidenza upload BE e shape di ritorno Box
- lookup `GET /api/v1/uploads/{upload_id}/links` gia usato dal gateway prima della completion
- issue residua non nel perimetro gateway:
  - `be` restituisce link documento con host locale MinIO (`localhost:9000`) oppure `download_url` non immediatamente consumabile da OPC
  - il gateway compensa costruendo un URL BE assoluto, ma la raggiungibilita reale del documento va corretta lato `be`/storage exposure
