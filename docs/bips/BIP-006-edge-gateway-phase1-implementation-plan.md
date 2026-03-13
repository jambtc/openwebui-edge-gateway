# BIP-006 - Edge Gateway Fase 1: piano tecnico implementazione

> Stato attuale: `🔄 In Esecuzione` - avvio 2026-03-13
> Owner: `proxy` team

## Obiettivo Fase 1

Implementare l'intercetto hard di upload Box su `/api/v1/files*` mantenendo la compatibilita FE.

Target:
- il file non resta nel dominio documentale Box
- upload reale su `proxy -> be`
- FE continua a vedere API files Box-compatible

## Topologia target

- Northbound (browser -> gateway):
  - tutte le chiamate Box passano da gateway (stesso host pubblico Box)
- Southbound (gateway -> upstream):
  - pass-through default verso Box backend
  - route upload deviate verso BE tramite bridge proxy

## Routing matrix Fase 1

1. `POST /api/v1/files`:
- intercept + transform
- forward multipart a `proxy /v1/uploads/bridge` (o diretto `be /api/v1/uploads` se deciso)
- risposta adattata a shape Box file model

2. `GET /api/v1/files/{id}/process/status?stream=true`:
- intercept
- SSE compatibile (`pending/completed/failed`) basata su stato bridge

3. `GET /api/v1/files/{id}` (opzionale Fase 1, consigliata):
- intercept
- metadata file da mapping gateway

4. `GET /api/v1/files/{id}/content` (opzionale Fase 1, consigliata):
- intercept
- proxy download da `be` (download_url/public_url)

5. Tutte le altre route `/api/*`:
- pass-through trasparente verso Box backend

## Adapter risposta upload (compatibilita FE)

FE Box si aspetta campi tipo:
- `id`
- `user_id`
- `filename`
- `meta` (`name`, `content_type`, `size`, `data`)
- `data.status`
- `status`
- `created_at`, `updated_at`

BE ritorna campi tipo:
- `upload_id`, `filename`, `mime_type`, `size_bytes`, `metadata`, `status`, `download_url`, `public_url`

Il gateway deve produrre una risposta compatibile FE mappando:
- `id <- upload_id` (o `bridge_upload_id` se serve alias)
- `meta.content_type <- mime_type`
- `meta.size <- size_bytes`
- `meta.data.be_upload <- {...}` (public_url, download_url, object_key)
- `data.status <- completed` (o stato corrente)

## Persistenza tecnica nel gateway

Serve tabella/kv di correlazione (es. sqlite/postgres/redis):
- chiave: `box_file_id` (id esposto a FE)
- campi: `be_upload_id`, `user_id`, `filename`, `mime_type`, `size`, `status`, `download_url`, `public_url`, `created_at`, `updated_at`

Uso:
- rispondere a `/process/status`
- risolvere `/files/{id}` e `/content`
- supportare Fase 2 (`GET /api/v1/uploads` + rewrite completion)

## Sicurezza e trust boundaries

- propagare `Authorization` e `X-Debug-User` solo dove necessario
- non loggare payload file raw
- aggiungere correlation-id per tracing (`x-request-id`, `bridge_upload_id`)
- validare mime/size lato gateway prima forward

## Rollout

1. Shadow mode (opzionale): log-only su `/api/v1/files` senza bloccare flusso.
2. Canary: intercetto per subset utenti/tenant.
3. Full switch: intercetto totale `/api/v1/files*`.
4. Stabilizzazione: metriche error-rate/latency e audit shape response FE.

## Test minimi

- upload txt/pdf su chat nuova
- `process/status?stream=true` senza errori FE
- invio messaggio con file allegato (chat non regressa)
- download/preview file da FE (se endpoint content coperto in fase)
- fallback error handling se BE non disponibile

## Non-obiettivi Fase 1

- inject automatico OPC
- riscrittura completions con public_url (Fase 2)
- copertura totale di tutte le route Box custom

## Deliverable

- router edge per `/api/v1/files*`
- adapter response Box-compatible
- store correlazione file
- test e checklist regressione FE upload
- documentazione operativa deploy e rollback

## Avanzamento

### 2026-03-13 - Avvio implementazione POC

- Implementate nel proxy route edge compatibili files API Box:
  - `POST /api/v1/files` (+ slash variant)
  - `GET /api/v1/files/{file_id}`
  - `GET /api/v1/files/{file_id}/process/status`
  - `GET /api/v1/files/{file_id}/content`
  - `GET /api/v1/files/{file_id}/content/html`
- Implementato adapter risposta upload BE -> shape Box (`status + file model`).
- Implementato store in-memory POC per stato file/process e mapping metadata.
- `process/status?stream=true` gestito con SSE compatibile (evento `status`).
- Nota: persistenza e policy production-grade restano step successivi (store persistente + rollout).

### 2026-03-13 - Estensione edge pass-through

- Introdotto catch-all pass-through HTTP per route non intercettate verso Box upstream (`edge.box_base_url`).
- Aggiunta configurazione edge:
  - `edge.enabled`
  - `edge.box_base_url`
  - `edge.timeout_seconds`
- Validato wiring locale:
  - Browser -> gateway `localhost:3001`
  - gateway -> Box upstream `localhost:3002`

### 2026-03-13 - Evidenze runtime upload

- Log gateway con risposta BE upload completa (`upload_id`, `object_key`, `public_url`, `download_url`).
- Log gateway con risposta adattata Box (`meta.data.be_upload` valorizzato).
- Rotta `POST /api/v1/files` validata con `200` e `process/status` SSE `200`.

### 2026-03-13 - Compatibilita WebSocket FE

- Implementato pass-through WS su `/ws/socket.io/*` per il canale realtime Box.
- Versione libreria `websockets` gestita in modo compatibile (`extra_headers` / `additional_headers`).
