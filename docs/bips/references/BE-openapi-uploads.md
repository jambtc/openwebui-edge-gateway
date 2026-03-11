# BE OpenAPI Reference - Uploads + Inject

Data estrazione: 2026-03-11

Fonte:
- `swagger-backend.json`
- OpenAPI `3.1.0`
- API title: `OpenClaw BFF`

## Endpoint principali per il flow documenti

### Upload multipart (principale)

- `POST /api/v1/uploads`
- Content-Type: `multipart/form-data`
- Request body schema: `Body_upload_file_multipart_api_v1_uploads_post`

Campi form supportati:
- `file` (required)
- `metadata_json` (string JSON, opzionale)
- `tags` (string CSV, opzionale)
- `include_presigned_get` (boolean, opzionale)
- `presigned_get_expires_seconds` (integer, opzionale)

Response `200`:
- schema `UploadCreateResponse`
- campi chiave: `upload_id`, `filename`, `mime_type`, `size_bytes`, `sha256`, `download_url`, `public_url`, `presigned_get_url`

### Inject context nella conversazione (per OPC)

- `POST /api/v1/conversations/{conversation_id}/inject`
- Request body schema: `InjectRequest`
  - `content` (required)
  - `label` (optional)
- Response `200`: `InjectResponse`
  - `injected: boolean`
  - `openclaw_result: object|null`

Nota operativa:
- l'inject richiede `conversation_id` (UUID BE), non `chat_id` Box.

## Endpoint secondari utili

- `GET /api/v1/uploads` (lista/ricerca)
- `GET /api/v1/uploads/{upload_id}` (dettaglio)
- `GET /api/v1/uploads/{upload_id}/links` (download/public/presigned)
- `GET /api/v1/uploads/{upload_id}/download` (stream download)
- `PUT /api/v1/uploads/{upload_id}/content` (replace multipart)
- `PATCH /api/v1/uploads/{upload_id}` (metadata DB-only)
- `DELETE /api/v1/uploads/{upload_id}` (soft/hard delete)

## Header/auth osservati nello swagger

Quasi tutti gli endpoint includono:
- `Authorization` (optional in schema)
- `X-Debug-User` (optional in schema, modalita DEV)

Interpretazione pratica:
- in ambienti con Keycloak attivo, il token Bearer resta necessario lato runtime.
- per integrazione proxy->be conviene prevedere auth tecnica esplicita (service token o trusted network), non affidarsi al fatto che in schema sia `required=false`.

## Implicazioni per BIP-003

1. Il proxy puo usare direttamente `POST /api/v1/uploads` come endpoint upload backend.
2. Dopo upload, il proxy puo chiamare `POST /api/v1/conversations/{conversation_id}/inject`.
3. Resta da risolvere il mapping affidabile `box_chat_id -> be conversation_id` (prerequisito funzionale).
