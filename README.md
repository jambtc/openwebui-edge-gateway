# OpenClaw OpenAI Proxy (towards OpenWebUI Edge Gateway)

Questo repository nasce come OpenAI-compatible proxy (`boxedai -> proxy -> be -> openclaw`),
ma il requisito prodotto emerso sul flusso documenti ha cambiato il perimetro:

- il caricamento `POST /api/v1/files` deve essere intercettato
- il file non deve restare nel dominio Box
- il percorso target deve essere `box -> proxy -> be` (RAG documentale)

Per questo il progetto evolve verso un vero **Edge Gateway** davanti a OpenWebUI.

Nome target repository (proposto): **`openwebui-edge-gateway`**.

## Perche il pivot

Con le sole Function OpenWebUI (anche avanzate) non si intercetta direttamente
`/api/v1/files`: le Function operano nel percorso chat/completions, non sui router
HTTP files del backend Box.

Quindi per il requisito upload serve un layer L7 che intercetti route API,
con due opzioni:

1. fork Box (FE/BE) con reroute upload
2. reverse proxy/API gateway davanti a Box che intercetta `/api/v1/files*`

## Stato attuale implementato

- Routing OpenAI-compatible verso BE:
  - `/v1/chat/completions`
  - `/v1/completions`
  - `/v1/responses` (con fallback su chat/completions se upstream non disponibile)
- Bridge upload BE:
  - `/v1/uploads/bridge` (alias `/uploads/bridge`) -> `be /api/v1/uploads`
- Edge upload compatibility (POC Fase 1):
  - `POST /api/v1/files`
  - `GET /api/v1/files/{id}`
  - `GET /api/v1/files/{id}/process/status`
  - `GET /api/v1/files/{id}/content`
- Session bridge function lato Box (`body.user = sha256(user_id:chat_id)`).

## Nuovo scope (Edge Gateway)

Scope prioritario:

1. Intercettare `POST /api/v1/files` (e route collegate) a livello gateway.
2. Inoltrare upload a `proxy -> be` e restituire shape compatibile al FE Box.
3. Prima della completion, risolvere `public_url` via `GET /api/v1/uploads` e arricchire il messaggio.

Dettaglio operativo e decisioni nei BIP sotto `docs/bips`.

## BIP di riferimento

- `BIP-001`: visione full-routing
- `BIP-002`: intercetto upload Box `/api/v1/files*`
- `BIP-003`: upload bridge + inject (attualmente sospesa parte inject)
- `BIP-004`: correlazione file/chat + lookup upload pre-completion
- `BIP-005`: scope ufficiale Edge Gateway
- `BIP-006`: implementazione tecnica Fase 1 edge (upload + pass-through)

## Documentazione operativa

- Contesto operativo: `docs/00-contesto-iniziale.md`
- Data flow e diagrammi (container + porte): `docs/documentazione/01-flusso-dati-edge-gateway.md`
- BIP index: `docs/bips/README.md`

## Avvio locale

```bash
cd /var/www/openclaw-openai-proxy
python -m venv .venv && source .venv/bin/activate
pip install -e .
OPENCLAW_PROXY_CONFIG=config.yaml openclaw-openai-proxy
```

Servizio di default: `0.0.0.0:4010`.

## Edge passthrough verso Box

Per usare il gateway come reverse proxy edge davanti a OpenWebUI (Box),
abilita in `config.yaml`:

```yaml
edge:
  enabled: true
  box_base_url: "${BOX_BASE_URL}"
  timeout_seconds: 120
```

Con questa opzione, tutte le route non gestite localmente dal gateway
vengono inoltrate a Box. Le route intercettate localmente (es. `/api/v1/files*`
e OpenAI-compatible) restano sotto controllo gateway.

In `.env` puoi quindi variare facilmente la porta locale Box, ad esempio:

```bash
BOX_BASE_URL=http://host.docker.internal:3002
```
