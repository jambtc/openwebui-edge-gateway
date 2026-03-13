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
- routing OpenAI compatibile attivo verso BE:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/responses` (con fallback su chat/completions)
- edge pass-through attivo per route non intercettate (gateway davanti a Box)

## Porte e servizi (topologia locale test)

- `opc-proxy` (gateway):
  - `3001 -> 4010` (entrypoint FE/API)
  - `4010 -> 4010` (entrypoint provider OpenAI-compatible)
- `open-webui` (boxedai backend):
  - `3002 -> 8080` (upstream del gateway)
- `mvp-qdrant`:
  - `6333 -> 6333`
- `be` remoto:
  - `https://be-boxedai-contabo.theia-innovation.com` (443)
- `openclaw` runtime (a valle BE):
  - `18789` / `18789/ws` (infrastruttura runtime)

Nota: in locale il browser usa `http://localhost:3001` (gateway). Il gateway inoltra a Box su `BOX_BASE_URL` (attualmente `http://host.docker.internal:3002`).

## Invarianti tecniche

- nessuna regressione UX lato Box su chat/upload
- mapping file conservato nel gateway (`meta.data.be_upload`)
- log applicativi con evidenza upload BE e shape di ritorno Box
- prossima fase: lookup `GET /api/v1/uploads` + inject `public_url` prima della completion
