# OpenWebUI Edge Gateway

Gateway applicativo davanti a OpenWebUI per BoxedAI.

Funzione attuale del software:

- intercettare le route Box che devono uscire dal dominio OpenWebUI
- inoltrare upload e completion al `be`
- mantenere compatibilita con frontend Box, WebSocket e OIDC
- reiniettare il contesto documento sulla completion reale emessa da Box

Flusso operativo corrente:

- `BR -> gateway -> box/be -> opc`

## Cosa fa oggi

- intercetta `POST /api/v1/files`
- serve le route compatibili Box per stato e contenuto file
- intercetta `POST /api/v1/chats/new` e `POST|PUT|PATCH /api/v1/chats/{chat_id}`
- intercetta `POST /api/chat/completions` e `POST /api/v1/chat/completions`
- inoltra al `be`:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/responses` con fallback su chat completions se upstream non disponibile
- esegue pass-through WebSocket su `/ws/socket.io/*`
- esegue catch-all HTTP verso Box per le route non intercettate
- mantiene funzionante il login OIDC/Keycloak dietro gateway

## Stato attuale noto

- model esposto a Box: `main`
- agent effettivo inoltrato al `be`: `assistant`
- priorita URL documento nel gateway:
  1. `presigned_get_url`
  2. `public_url`
  3. `download_url`

Limite residuo noto:

- il `be` continua a restituire `public_url` / `presigned_get_url` con host locale `localhost:9000`
- quindi il punto aperto residuo e lato `be` / MinIO exposure, non lato gateway

## Documentazione corrente

- Contesto operativo: [docs/00-contesto-iniziale.md](/var/www/openwebui-edge-gateway/docs/00-contesto-iniziale.md)
- Flusso dati e infrastruttura: [docs/documentazione/01-flusso-dati-edge-gateway.md](/var/www/openwebui-edge-gateway/docs/documentazione/01-flusso-dati-edge-gateway.md)
- Rollout VPS: [docs/documentazione/02-modifiche-vps-rollout.md](/var/www/openwebui-edge-gateway/docs/documentazione/02-modifiche-vps-rollout.md)
- Verifica allineamento: [docs/documentazione/03-verifica-allineamento-software.md](/var/www/openwebui-edge-gateway/docs/documentazione/03-verifica-allineamento-software.md)

## Storico e roadmap

Per l'evoluzione del progetto e le decisioni progressive:

- [docs/archivio/README.md](/var/www/openwebui-edge-gateway/docs/archivio/README.md)
- [docs/bips/README.md](/var/www/openwebui-edge-gateway/docs/bips/README.md)

## Avvio consigliato: Docker Compose

La configurazione consigliata oggi e `docker compose`.

Motivi:

- espone il gateway sulle porte giuste per il test locale:
  - `3001 -> 4010` per il traffico browser / Box pubblico
  - `4010 -> 4010` per il provider OpenAI-compatible
- carica automaticamente `.env`
- usa `config.yaml` come configurazione runtime del gateway
- rende parametrico anche il target backend tramite `BACKEND_BASE_URL`
- abilita o disabilita il vero streaming backend tramite `BACKEND_STREAMING_ENABLED`
- monta il container `opc-proxy` sulla rete Docker condivisa `tradarb_default`
- mantiene il wiring coerente con Box locale su `BOX_BASE_URL`

Prerequisiti:

- rete Docker esterna presente: `tradarb_default`
- Box locale raggiungibile all'URL definito in `.env`, oggi:
  - `BOX_BASE_URL=http://host.docker.internal:3002`
- backend locale o VPS raggiungibile all'URL definito in `.env`, oggi:
  - `BACKEND_BASE_URL=http://127.0.0.1:8000`
- toggle streaming backend definito in `.env`, oggi:
  - `BACKEND_STREAMING_ENABLED=false`

Avvio:

```bash
cd /var/www/openwebui-edge-gateway
docker compose up -d --build
```

Verifica rapida:

```bash
docker ps --filter name=opc-proxy
curl http://localhost:3001/healthz
curl http://localhost:4010/v1/models
```

Comportamento atteso:

- `http://localhost:3001` e l'entrypoint del gateway per il browser
- `http://localhost:4010` espone le route OpenAI-compatible del gateway
- il container avviato e `opc-proxy`

Nota operativa:

- se Box gira su una porta host diversa, aggiorna `BOX_BASE_URL` nel file `.env` prima del `docker compose up`
- se il backend non e locale su `127.0.0.1:8000`, aggiorna `BACKEND_BASE_URL` nel file `.env`
- se vuoi rispettare `stream=true` nelle completion, imposta `BACKEND_STREAMING_ENABLED=true`
- in VPS, invece di `host.docker.internal:3002`, il valore consigliato per Box resta `http://open-webui:8080`

## Avvio locale alternativo: venv

Utile solo per sviluppo locale senza container.

```bash
cd /var/www/openwebui-edge-gateway
python -m venv .venv && source .venv/bin/activate
pip install -e .
OPENCLAW_PROXY_CONFIG=config.yaml openclaw-openai-proxy
```

Servizio di default: `0.0.0.0:4010`.
