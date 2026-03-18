# Flusso Dati Edge Gateway (container, porte, route)

Data aggiornamento: 2026-03-17

## Executive summary

Il gateway `opc-proxy` e il punto di ingresso corretto per BoxedAI.

In VPS, se il dominio pubblico Box e servito da `Caddy`, l'upstream corretto del vhost deve essere:

- `opc-proxy:4010`

E non:

- `open-webui:8080`

Obiettivo raggiunto nel perimetro gateway:

- upload file intercettato su `POST /api/v1/files`
- inoltro reale a `be /api/v1/uploads`
- risposta adattata in shape Box-compatible
- correlazione chat/file mantenuta dal gateway
- reinject del riferimento documento sulla completion reale emessa da Box verso il provider `/v1/chat/completions`
- passthrough WebSocket su `/ws/socket.io/*`
- passthrough HTTP catch-all verso Box per tutte le route non intercettate
- supporto login OIDC/Keycloak dietro gateway, con preservazione di header `Set-Cookie` multipli e forwarding `Host` / `X-Forwarded-*`

Punto aperto residuo:

- il `be` restituisce ancora `public_url` e `presigned_get_url` con host locale (`localhost:9000`)
- il gateway oggi li propaga in priorita per test funzionale del flusso documentale
- la raggiungibilita reale del documento da parte di OPC resta quindi un tema `be` / MinIO exposure, non un tema gateway

## Nota sul perimetro documentale

Questo documento descrive il funzionamento corrente del sistema.

Per lo storico del pivot architetturale e la roadmap incrementale:

- [Archivio](/var/www/openwebui-edge-gateway/docs/archivio/README.md)
- [BIP](/var/www/openwebui-edge-gateway/docs/bips/README.md)

## Topologia runtime (locale test)

| Nodo | Container/Servizio | Porta | Ruolo |
| --- | --- | --- | --- |
| Browser | n/a | `localhost:3001` | entrypoint unico FE/API |
| Gateway | `opc-proxy` | `3001 -> 4010`, `4010 -> 4010` | edge routing + upload intercept + provider OpenAI-compatible |
| BoxedAI | `open-webui` | `3002 -> 8080` | backend Open WebUI (route API non intercettate) |
| LLM locale Box | `ollama` | `11434` interno Docker | servizio locale Box, non pubblicato nel compose test |
| Vector DB | `mvp-qdrant` | `6333 -> 6333` | storage embedding/retrieval Box |
| BE | `be-boxedai` remoto | `443` | API backend upload/completions |
| BE app (dev) | processo FastAPI | `8000` | porta applicativa BFF quando avviato con `scripts/dev_run.sh` |
| BE DB | `openclaw_bff_postgres` | `5432 -> 5432` | Postgres |
| BE storage | `openclaw_bff_minio` | `9000 -> 9000`, `9001 -> 9001` | object storage + console |
| BE auth | `openclaw_bff_keycloak` | `8080 -> 8080` | autenticazione OIDC |
| OPC runtime | esterno | `18789` / `18789/ws` | runtime agent a valle del BE |

## Modello esposto dal gateway

Configurazione attuale del gateway:

- model esposto a Box: `main`
- `agent_id` reale inoltrato a OpenClaw/BE: `assistant`

Quindi il gateway pubblica `main` in `/v1/models`, ma prima dell'inoltro verso il `be` normalizza il payload in:

- `openclaw:assistant`

Questo comportamento e coerente con [config.yaml](/var/www/openwebui-edge-gateway/config.yaml).

## Schema infrastruttura completa

```mermaid
flowchart TB
    BR[Browser
boxedai-contabo / localhost:3001]
    C[Caddy / Reverse Proxy Pubblico
VPS]
    G[opc-proxy
container gateway
:4010]
    B[open-webui
container Box
:8080]
    Q[mvp-qdrant
:6333]
    O[ollama
:11434 interno]
    BE[BE API
https :443
app dev :8000]
    KC[keycloak
:8080]
    PG[postgres
:5432]
    M[minio
:9000 API
:9001 console]
    OPC[OpenClaw runtime
:18789 /ws]

    BR -->|HTTPS| C
    C -->|upstream Box pubblico| G
    G -->|catch-all HTTP| B
    G -->|upload + completions| BE
    G -->|WS passthrough| B
    B --> Q
    B --> O
    BE --> KC
    BE --> PG
    BE --> M
    BE --> OPC
```

## Schema generale (grafico)

```mermaid
flowchart LR
    BR[Browser\nlocalhost:3001] --> G[opc-proxy\n:4010]

    G -->|pass-through default| B[open-webui\n:8080 (host:3002)]
    G -->|upload/completions| BE[be-boxedai-contabo\nhttps :443]
    B --> O[ollama\n:11434 interno]
    B --> Q[mvp-qdrant\n:6333]
    BE --> OPC[OpenClaw runtime\n:18789 /ws]
    BE --> PG[postgres\n:5432]
    BE --> M[minio\n:9000 / :9001]
    BE --> KC[keycloak\n:8080]
```

## Route intercettate dal gateway

Route edge/browser-side:

- `POST /api/v1/files`
- `GET /api/v1/files/{file_id}`
- `GET /api/v1/files/{file_id}/process/status`
- `GET /api/v1/files/{file_id}/content`
- `GET /api/v1/files/{file_id}/content/html`
- `POST /api/v1/chats/new`
- `POST|PUT|PATCH /api/v1/chats/{chat_id}`
- `POST /api/chat/completions`
- `POST /api/v1/chat/completions`
- `GET|POST|PUT|PATCH|DELETE|OPTIONS|HEAD /*` non intercettato localmente -> passthrough a Box
- `WS /ws/socket.io/*` -> passthrough a Box

Route OpenAI-compatible/provider-side:

- `GET /v1/models`
- `POST /v1/chat/completions`
- `POST /v1/completions`
- `POST /v1/responses`
- alias senza prefisso `/v1`: `/models`, `/chat/completions`, `/completions`, `/responses`

## Flusso upload file (implementato)

```mermaid
sequenceDiagram
    participant BR as Browser (Box FE)
    participant G as Gateway (opc-proxy)
    participant BE as BE uploads API
    participant M as MinIO (BE storage)

    BR->>G: POST /api/v1/files?process=true (multipart/form-data)
    G->>BE: POST /api/v1/uploads (multipart + user headers)
    BE->>M: Salvataggio oggetto
    BE-->>G: JSON upload (upload_id, object_key, public_url, presigned_get_url, ...)
    G-->>BR: JSON Box-compatible + meta.data.be_upload
    BR->>G: GET /api/v1/files/{id}/process/status?stream=true
    G-->>BR: SSE status=completed
```

## Flusso chat/completions (corrente)

```mermaid
sequenceDiagram
    participant BR as Browser
    participant G as Gateway
    participant B as Box backend
    participant BE as BE
    participant OPC as OpenClaw

    BR->>G: POST /api/chat/completions
    G->>B: pass-through /api/chat/completions (payload gia arricchito se possibile)
    B->>G: POST /v1/chat/completions (provider OpenAI)
    G->>BE: POST /v1/chat/completions
    BE->>OPC: elaborazione agent
    OPC-->>BE: risposta
    BE-->>G: risposta OpenAI-compatible
    G-->>B: risposta
    B-->>BR: risposta chat
```

## Flusso completo documento + chat (implementato nel gateway)

```mermaid
sequenceDiagram
    participant BR as Browser
    participant G as Gateway
    participant B as Box backend
    participant BE as BE
    participant OPC as OpenClaw

    BR->>G: POST /api/v1/files?process=true
    G->>BE: POST /api/v1/uploads
    BE-->>G: upload_id + links
    G-->>BR: risposta files Box-compatible
    BR->>G: POST /api/v1/chats/new
    G->>B: passthrough
    B-->>G: chat.id persistito
    G->>G: salva mapping chat_id -> file_id/upload_id
    BR->>G: POST /api/chat/completions
    G->>BE: GET /api/v1/uploads/{upload_id}/links
    G->>G: prepara documento da iniettare
    G-->>B: inoltra payload Box arricchito
    B->>G: POST /v1/chat/completions
    G->>G: reinject provider-side sulla completion reale
    G->>BE: POST /v1/chat/completions
    BE->>OPC: esecuzione agente
    OPC-->>BE: risposta
    BE-->>G: risposta OpenAI-compatible
    G-->>B: risposta
    B-->>BR: risposta finale
```

## Flusso OIDC / Keycloak dietro gateway (implementato)

```mermaid
sequenceDiagram
    participant BR as Browser
    participant G as Gateway
    participant B as Box backend
    participant KC as Keycloak

    BR->>G: GET /auth
    G->>B: passthrough
    B-->>BR: pagina login Box
    BR->>KC: login OIDC
    KC-->>BR: redirect verso /oauth/oidc/callback
    BR->>G: GET /oauth/oidc/callback?...code=...
    G->>B: passthrough callback OIDC
    B-->>G: 302 + Set-Cookie multipli
    G-->>BR: 302 + Set-Cookie multipli preservati
    BR->>G: GET /
    G->>B: passthrough con cookie di sessione
    B-->>BR: sessione autenticata
```

Note implementative rilevanti:

- il gateway preserva `Set-Cookie` multipli nella response upstream
- il gateway inoltra `Host`, `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Port`
- questo e necessario per non rompere la sessione OIDC dietro edge gateway

## Evidenza runtime upload e inject (log gateway)

Dal test E2E:

- `POST /api/v1/files/?process=true` `200 OK`
- `GET /api/v1/files/{id}/process/status?stream=true` `200 OK`
- `POST /api/v1/chats/new` intercettata e correlata con `chat_id`
- `POST /api/chat/completions` intercettata con payload browser-side
- `/v1/chat/completions` finale reintegrata con contesto documento dal gateway
- payload BE acquisito con campi: `upload_id`, `object_key`, `download_url`, `public_url`, `presigned_get_url`
- payload Box ritornato con:
  - `id = upload_id`
  - `meta.data.be_upload.*` (metadati BE riutilizzabili in fase completion)
- logs chiave disponibili:
  - `EDGE upload -> BE ...`
  - `EDGE chats.new sync ...`
  - `EDGE browser chat.forward ...`
  - `EDGE provider.pending ...`
  - `proxy→be pending.documents ...`
  - `EDGE upload.links ...`

## Formato inject documento (corrente)

Il gateway aggiunge il riferimento documento all'ultimo messaggio `user` in forma testuale:

```text
Attached documents:
Use these document URLs as the primary source for this request.
If you need the file content, perform an internal curl/HTTP GET from your runtime to the document URL below and inspect the returned content.
Do not ask the user to upload the file again if a document URL is already present.
- powerskid.pdf: http://...
```

Questo inject avviene:

1. browser-side su `POST /api/chat/completions`
2. provider-side sulla vera `POST /v1/chat/completions` emessa da Box, se Box ricostruisce il payload e perde l'inject precedente

## Priorita URL documento nel codice attuale

Il gateway oggi costruisce l'URL documento in questo ordine:

1. `presigned_get_url`
2. `public_url`
3. `download_url`

Questo e il comportamento reale del codice attuale.

Nota importante: oggi `presigned_get_url` e `public_url` tornano ancora con host `localhost:9000`, quindi il gateway puo iniettare URL non consumabili da OPC fuori dal network del `be`. Questo non e un mismatch documentale: e il comportamento corrente del software, usato per verificare il punto di rottura residuo lato `be`.

## Limitazione residua

Il gateway ha chiuso il problema di intercetto, correlazione, reinject, WebSocket e OIDC passthrough.

Resta aperto lato `be` / storage:

- `GET /api/v1/uploads/{upload_id}/links` restituisce ancora:
  - `public_url` con host locale MinIO (`localhost:9000`)
  - `presigned_get_url` anch'esso su host locale
- OPC rifiuta `localhost` / reti interne per policy del runtime
- quindi il flusso si interrompe non nel gateway, ma sulla consumabilita finale dell'URL documento

Conclusione operativa:

- il software del gateway e coerente con questo documento
- il prossimo fix di piattaforma non e nel gateway ma nel `be` / exposure MinIO / download pubblico effettivo
