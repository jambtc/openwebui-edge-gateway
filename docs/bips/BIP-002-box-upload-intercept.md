# BIP-002 - Box upload intercept (`/api/v1/files`) verso proxy

> Stato attuale: `📋 Proposta` - 2026-03-11
> Owner: `box + proxy` team

## Contesto

Nel frontend BoxedAI, il click sul pulsante `+` usa upload interno su:

- `POST /api/v1/files/?process=true`
- `content-type: multipart/form-data`

Dallo studio del codice (`backend/open_webui/routers/files.py`) risulta che questo flow:
- salva il file su storage locale Box
- crea record file interno Box
- opzionalmente processa il file lato retrieval

Questo percorso non passa dai filtri chat usati per le completions, quindi non e intercettabile con la sola Filter Function chat.

## Proposta

Aggiungere in Box una funzione di relay upload (hook applicativo) nel flow di `upload_file_handler`:

1. Dopo upload locale riuscito, costruire payload multipart con file + metadata minimi.
2. Inviare il documento al proxy su endpoint dedicato (nuovo), ad esempio:
   - `POST /v1/uploads/bridge`
3. Trasmettere metadata necessari alla correlazione sessione:
   - `box_user_id`
   - `box_chat_id` (se disponibile)
   - `box_file_id`
   - filename/content_type/size
4. Non bloccare UX upload Box in caso di errore bridge (modalita best-effort iniziale), ma tracciare stato sync.

## Impatto atteso

- Tutti i documenti caricati da Box vengono propagati nel flow `box -> proxy -> be -> opc`.
- Si riduce il gap attuale in cui il documento resta solo nel dominio Box.
- Preparazione per context injection automatica su stessa sessione.

## Rischi

- Aumento latenza upload lato Box se relay sincrono.
- Fallimenti di rete proxy/be durante upload.
- Metadata incompleti (mancanza `chat_id`) che impediscono collegamento sessione.

## Criteri di accettazione

- Ogni upload su `POST /api/v1/files/?process=true` genera tentativo relay verso proxy.
- Proxy riceve multipart valido e risponde con tracking id.
- Box mantiene upload locale funzionante anche se relay fallisce (fase iniziale).
- Stato relay tracciabile in log con correlazione `box_file_id`.

## Dipendenze

- Definizione endpoint upload bridge nel proxy (BIP-003).
- Contratto payload/response proxy-be condiviso.

## Avanzamento

### 2026-03-11 - Analisi iniziale

- Confermato endpoint upload reale di Box: `/api/v1/files/?process=true`.
- Confermato che il flusso e gestito nel backend Box (`routers/files.py`) e non dai filtri chat.
- Definita proposta di hook relay verso proxy.
