# Modifiche VPS e Rollout Operativo

Data aggiornamento: 2026-03-13

## Obiettivo

Portare in VPS il wiring corretto:

- dominio Box pubblico davanti al gateway
- Box dietro al gateway come upstream interno
- flusso applicativo reale:
  - `browser -> gateway -> box/be -> opc`

## Stato target in VPS

### 1. Entry point pubblico

Il dominio Box pubblico non deve piu puntare direttamente a `open-webui`.

Deve invece puntare a:

- `opc-proxy` se il reverse proxy esterno inoltra direttamente al container gateway
- oppure alla porta host mappata dal gateway

Obiettivo pratico:

- `https://boxedai-contabo.theia-innovation.com` -> gateway

### 1.b Caddy: upstream corretto

Se in VPS il reverse proxy pubblico e `Caddy`, il vhost del dominio Box deve puntare al container:

- `opc-proxy`

Non deve piu puntare al container:

- `open-webui`

Motivo:

- se Caddy punta a `open-webui`, il flusso upload/chat bypassa il gateway
- in quel caso il gateway non puo intercettare:
  - `POST /api/v1/files`
  - `POST /api/v1/chats/new`
  - `POST /api/chat/completions`

Target corretto lato Caddy:

- `boxedai-contabo.theia-innovation.com` -> `opc-proxy:4010`

Target errato da evitare:

- `boxedai-contabo.theia-innovation.com` -> `open-webui:8080`

### 2. Box come upstream interno

`open-webui` deve restare raggiungibile dal gateway, ma non essere la front-door pubblica principale.

Target consigliato:

- Box esposto solo su rete interna Docker
- oppure su porta host non pubblicata esternamente

Nel test locale il pattern e:

- browser -> `localhost:3001` -> gateway
- gateway -> `host.docker.internal:3002` -> Box

In VPS il pattern corretto e preferibilmente:

- reverse proxy pubblico -> `opc-proxy:4010`
- `opc-proxy` -> `open-webui:8080` su stessa rete Docker

## Variabili/configurazioni da allineare

### Gateway (`proxy`)

Nel repo `proxy`:

- file: `/var/www/openclaw-openai-proxy/.env`
- variabile:

```bash
BOX_BASE_URL=http://open-webui:8080
```

Se il gateway e sulla stessa rete Docker di Box, questo e il valore consigliato in VPS.

Nel file `config.yaml` del gateway:

```yaml
edge:
  enabled: true
  box_base_url: "${BOX_BASE_URL}"
  timeout_seconds: 120
```

### Box (`open-webui`)

Nel repo Box:

- file: `/var/www/open-webui/.env`

Variabili chiave:

```bash
WEBUI_URL='https://boxedai-contabo.theia-innovation.com'
OPENCLAW_OPENAI_PROXY='http://opc-proxy:4010'
```

Note:

- `WEBUI_URL` deve riflettere l'URL pubblico reale servito dal gateway
- `OPENCLAW_OPENAI_PROXY` deve puntare al gateway raggiungibile da Box
- se Box e gateway sono nella stessa rete Docker, usare nome container/servizio e non host pubblico

### Reverse proxy esterno della VPS

Se esiste gia un Nginx/Traefik/Caddy di frontiera:

- il dominio pubblico Box deve terminare sul gateway
- devono essere consentiti:
  - HTTP standard
  - WebSocket per `/ws/socket.io/*`
  - richieste upload multipart grandi quanto richiesto

Per Caddy, il backend/upstream da configurare sul sito Box e quindi:

```text
opc-proxy:4010
```

non:

```text
open-webui:8080
```

## Porte e container da conoscere

### Gateway / Box

| Servizio | Container | Porta container | Porta host attuale | Uso |
| --- | --- | --- | --- | --- |
| Gateway | `opc-proxy` | `4010` | `3001`, `4010` | front-door Box + provider OpenAI-compatible |
| Box | `open-webui` | `8080` | `3002` in locale test | backend Open WebUI upstream |
| Ollama | `ollama` | `11434` | non pubblicata | servizio locale Box |
| Qdrant | `mvp-qdrant` | `6333` | `6333` | vector DB Box |

### Backend (`be`)

| Servizio | Container/Processo | Porta | Uso |
| --- | --- | --- | --- |
| BE app | processo `uvicorn` | `8000` | API applicativa BFF |
| Postgres | `openclaw_bff_postgres` | `5432` | DB |
| MinIO API | `openclaw_bff_minio` | `9000` | object storage/S3 |
| MinIO console | `openclaw_bff_minio` | `9001` | console amministrativa |
| Keycloak | `openclaw_bff_keycloak` | `8080` | auth/OIDC |
| OPC runtime | servizio esterno | `18789`, `18789/ws` | runtime agente |

## Modifiche concrete da fare in VPS

### Modifica 1. Mettere il gateway davanti a Box

Da fare:

- far terminare il dominio pubblico Box sul gateway
- non lasciare il dominio Box puntato direttamente a `open-webui`
- se il reverse proxy pubblico e Caddy, cambiare l'upstream del sito Box da `open-webui:8080` a `opc-proxy:4010`

Esito atteso:

- ogni chiamata FE/API passa dal gateway
- il gateway intercetta `/api/v1/files`, `/api/v1/chats/*`, `/api/chat/completions`

### Modifica 2. Allineare `BOX_BASE_URL`

Da fare:

- impostare `BOX_BASE_URL` a un endpoint interno e stabile di Box

Valore consigliato:

```bash
BOX_BASE_URL=http://open-webui:8080
```

### Modifica 3. Allineare `OPENCLAW_OPENAI_PROXY` in Box

Da fare:

- configurare Box per chiamare il gateway e non un endpoint legacy

Valore consigliato:

```bash
OPENCLAW_OPENAI_PROXY=http://opc-proxy:4010
```

### Modifica 4. Verificare WebSocket pass-through

Da fare:

- verificare che il reverse proxy pubblico non interrompa `/ws/socket.io/*`

Motivo:

- il frontend Box usa WebSocket per stato e realtime
- senza pass-through corretto la UI si degrada o fallisce

### Modifica 5. Verificare limite upload del reverse proxy pubblico

Da fare:

- controllare che il reverse proxy pubblico accetti `multipart/form-data` con dimensione coerente ai documenti attesi

Motivo:

- il gateway intercetta davvero gli upload; il collo di bottiglia puo quindi diventare il reverse proxy di frontiera

## Punto aperto non-gateway

Il punto ancora aperto non e nel gateway ma nel `be`:

- `GET /api/v1/uploads/{upload_id}/links` restituisce ancora `public_url` e `presigned_get_url` con host locale MinIO (`localhost:9000`)
- il gateway per ora ripiega su `download_url` assolutizzato sul dominio pubblico del `be`
- la fruibilita reale del documento da parte di OPC dipende quindi da una correzione lato `be`/MinIO exposure

Tradotto operativamente:

- il gateway oggi fa quello che deve
- per chiudere il flusso documentale in produzione serve che il `be` esponga un URL documento realmente raggiungibile dal consumer finale

## Checklist finale pre-rollout

- [ ] il dominio Box pubblico termina sul gateway
- [ ] `BOX_BASE_URL` punta a Box interno
- [ ] `OPENCLAW_OPENAI_PROXY` punta al gateway
- [ ] WebSocket `/ws/socket.io/*` funzionante
- [ ] upload multipart accettato dal reverse proxy pubblico
- [ ] `POST /api/v1/files` visibile nei log del gateway
- [ ] `POST /api/v1/chats/new` visibile nei log del gateway
- [ ] `POST /api/chat/completions` visibile nei log del gateway
- [ ] reinject provider-side visibile nei log (`proxy→be pending.documents`)
- [ ] `be` restituisce un URL documento realmente consumabile
