from __future__ import annotations

import asyncio
import base64
from pathlib import Path
import hashlib
import json
import logging
import time
import uuid
from typing import Any, Dict
from datetime import datetime

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from .backend import BackendClient
from .config import AgentConfig
from .settings import build_runtime_settings

log = logging.getLogger(__name__)

settings = build_runtime_settings()
config = settings.app_config
backend_client = BackendClient(config)

app = FastAPI(title="OpenClaw OpenAI Proxy", version="0.1.0")

# In-memory mapping for edge upload compatibility endpoints (/api/v1/files*).
# This is a Phase-1 store and will be replaced by persistent storage.
EDGE_FILE_STORE: dict[str, dict[str, Any]] = {}


def _resolve_valves_path() -> Path | None:
    cfg_path = config.pipeline.__dict__.get("valves_config")
    if not cfg_path:
        return None
    raw_path = Path(cfg_path)
    if not raw_path.is_absolute():
        raw_path = settings.config_path.parent / raw_path
    return raw_path


def _load_valves_config() -> Dict[str, Any]:
    raw_path = _resolve_valves_path()
    if not raw_path:
        return {}

    try:
        return json.loads(raw_path.read_text())
    except FileNotFoundError:
        log.warning("Valves config %s not found", raw_path)
    except Exception:
        log.exception("Failed to load valves config from %s", raw_path)
    return {}


def _save_valves_config(payload: Dict[str, Any]) -> None:
    raw_path = _resolve_valves_path()
    if not raw_path:
        raise RuntimeError("valves_config path is not configured")

    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))


def _serialize_agent(agent: AgentConfig) -> Dict[str, Any]:
    return {
        "id": agent.id,
        "object": "model",
        "created": 0,
        "owned_by": "openclaw",
        "name": agent.name or agent.id,
        "description": agent.description,
        "metadata": {
            "agent_id": agent.agent_id,
            "tags": agent.tags,
            "profile_image_url": agent.profile_image_url,
        },
    }


def _serialize_pipeline() -> Dict[str, Any]:
    pipeline = config.pipeline
    return {
        "id": pipeline.id,
        "object": "pipeline",
        "name": pipeline.name,
        "type": "filter",
        "pipelines": pipeline.pipelines,
        "priority": pipeline.priority,
        "description": pipeline.description,
        "valves": bool(pipeline.__dict__.get("valves_config")),
    }


def _get_body(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Requests from Open WebUI pipelines use {"body": {...}}; plain OpenAI calls send the body directly.
    body = payload.get("body")
    if isinstance(body, dict):
        return body
    if isinstance(payload, dict):
        return payload
    return {}


def _get_chat_id(payload: Dict[str, Any], body: Dict[str, Any]) -> str | None:
    # WebUI may place __metadata__ at top-level OR inside body (depending on path).
    meta = payload.get("__metadata__") or body.get("__metadata__") or {}
    if isinstance(meta, dict):
        cid = meta.get("chat_id")
        return cid if isinstance(cid, str) and cid else None
    return None


def _get_user_id(payload: Dict[str, Any]) -> str:
    u = payload.get("__user__") or {}
    if isinstance(u, dict):
        return str(u.get("id") or u.get("email") or "anon")
    return "anon"


def _session_key(user_id: str, chat_id: str) -> str:
    # sha256(user_id:chat_id) => 64 hex chars
    return hashlib.sha256(f"{user_id}:{chat_id}".encode("utf-8")).hexdigest()


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await backend_client.close()


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    return {"status": "ok"}


# -------------------------
# OpenAI-compatible endpoints
# -------------------------
@app.get("/v1/models")
async def list_models() -> Dict[str, Any]:
    return {
        "object": "list",
        "data": [_serialize_agent(agent) for agent in config.agents],
        # Non-standard extension used by Open WebUI (handy for discovering pipelines)
        "pipelines": [_serialize_pipeline()],
    }


@app.get("/models")
async def list_models_alias() -> Dict[str, Any]:
    """Compatibility alias without /v1 prefix."""
    return await list_models()


def _resolve_agent(model_id: str) -> AgentConfig:
    for agent in config.agents:
        if agent.id == model_id:
            return agent
    raise ValueError(f"Unknown model id '{model_id}'")


def _normalize_openai_model(
    payload: Dict[str, Any], require_model: bool = True
) -> None:
    model_id = payload.get("model")
    if not model_id:
        if require_model:
            raise HTTPException(status_code=400, detail="Missing 'model' in payload")
        return

    if isinstance(model_id, str) and (
        model_id.startswith("openclaw:") or model_id.startswith("agent:")
    ):
        return

    try:
        agent = _resolve_agent(model_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    payload["model"] = f"openclaw:{agent.agent_id}"


def _is_upstream_not_found(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    detail = payload.get("detail")
    if isinstance(detail, dict):
        return str(detail.get("raw", "")).strip().lower() == "not found"
    if isinstance(detail, str):
        return detail.strip().lower() == "not found"
    return False


def _extract_responses_input_text(input_value: Any) -> str:
    if isinstance(input_value, str):
        return input_value

    if isinstance(input_value, list):
        chunks: list[str] = []
        for item in input_value:
            if isinstance(item, str):
                chunks.append(item)
                continue
            if not isinstance(item, dict):
                continue

            item_type = item.get("type")
            if item_type in {"input_text", "text"} and isinstance(item.get("text"), str):
                chunks.append(item["text"])
                continue

            content = item.get("content")
            if isinstance(content, str):
                chunks.append(content)
                continue
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, str):
                        chunks.append(part)
                    elif isinstance(part, dict) and isinstance(part.get("text"), str):
                        chunks.append(part["text"])
        text = "\n".join([c for c in chunks if c]).strip()
        if text:
            return text

    if isinstance(input_value, dict):
        if isinstance(input_value.get("text"), str):
            return input_value["text"]
        if isinstance(input_value.get("content"), str):
            return input_value["content"]

    return str(input_value or "")


def _build_chat_fallback_payload_from_responses(
    payload: Dict[str, Any]
) -> Dict[str, Any]:
    text = _extract_responses_input_text(payload.get("input"))
    if not text:
        raise HTTPException(
            status_code=400,
            detail="Unsupported /v1/responses input for fallback translation",
        )

    chat_payload: Dict[str, Any] = {
        "model": payload.get("model") or "openclaw",
        "messages": [{"role": "user", "content": text}],
        "stream": False,
    }

    # Preserve common generation controls when present.
    for source_key, target_key in (
        ("user", "user"),
        ("temperature", "temperature"),
        ("top_p", "top_p"),
        ("stop", "stop"),
        ("n", "n"),
    ):
        value = payload.get(source_key)
        if value is not None:
            chat_payload[target_key] = value

    mot = payload.get("max_output_tokens")
    if mot is not None:
        chat_payload["max_tokens"] = mot

    return chat_payload


def _chat_completion_to_responses_shape(
    chat_payload: Dict[str, Any], chat_result: Dict[str, Any]
) -> Dict[str, Any]:
    choices = chat_result.get("choices") or []
    first_choice = choices[0] if choices else {}
    message = first_choice.get("message") if isinstance(first_choice, dict) else {}
    content = message.get("content") if isinstance(message, dict) else ""

    if isinstance(content, list):
        output_text = " ".join(str(x) for x in content)
    elif isinstance(content, str):
        output_text = content
    else:
        output_text = str(content or "")

    usage = chat_result.get("usage") or {}
    return {
        "id": f"resp_{uuid.uuid4().hex}",
        "object": "response",
        "created_at": chat_result.get("created") or int(time.time()),
        "status": "completed",
        "model": chat_result.get("model") or chat_payload.get("model"),
        "output": [
            {
                "id": f"msg_{uuid.uuid4().hex}",
                "type": "message",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": output_text,
                        "annotations": [],
                    }
                ],
            }
        ],
        "output_text": output_text,
        "usage": {
            "input_tokens": usage.get("prompt_tokens", 0),
            "output_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        },
    }


def _to_epoch_seconds(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except ValueError:
            pass
    return int(time.time())


def _try_decode_unverified_jwt_user_id(auth_header: str | None) -> str | None:
    if not auth_header:
        return None
    if not auth_header.lower().startswith("bearer "):
        return None
    token = auth_header.split(" ", 1)[1].strip()
    parts = token.split(".")
    if len(parts) < 2:
        return None

    payload_part = parts[1]
    padding = "=" * (-len(payload_part) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload_part + padding).decode("utf-8")
        payload = json.loads(decoded)
    except Exception:
        return None

    for key in ("id", "user_id", "sub", "uid", "email"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _edge_user_id_from_request(request: Request) -> str:
    for header_name in ("x-debug-user", "x-openwebui-user-id"):
        value = request.headers.get(header_name)
        if value:
            return value

    jwt_user = _try_decode_unverified_jwt_user_id(request.headers.get("authorization"))
    if jwt_user:
        return jwt_user
    return "edge-user"


def _edge_backend_headers_from_request(request: Request, user_id: str) -> dict[str, str]:
    headers = _bridge_headers_from_request(request)
    if "x-debug-user" not in headers and user_id:
        headers["x-debug-user"] = user_id
    return headers


def _adapt_be_upload_to_box_shape(be_payload: dict[str, Any], user_id: str) -> dict[str, Any]:
    file_id = str(be_payload.get("upload_id") or uuid.uuid4())
    filename = str(be_payload.get("filename") or "uploaded-file")
    mime_type = be_payload.get("mime_type")
    size_bytes = be_payload.get("size_bytes")
    created_at = _to_epoch_seconds(be_payload.get("created_at"))
    updated_at = _to_epoch_seconds(be_payload.get("updated_at"))

    be_meta = {
        "upload_id": be_payload.get("upload_id"),
        "bucket": be_payload.get("bucket"),
        "object_key": be_payload.get("object_key"),
        "download_url": be_payload.get("download_url"),
        "public_url": be_payload.get("public_url"),
        "presigned_get_url": be_payload.get("presigned_get_url"),
    }

    file_model = {
        "id": file_id,
        "user_id": user_id,
        "hash": be_payload.get("sha256"),
        "filename": filename,
        "data": {"status": "pending"},
        "meta": {
            "name": filename,
            "content_type": mime_type,
            "size": size_bytes,
            "data": {"be_upload": be_meta},
        },
        "created_at": created_at,
        "updated_at": updated_at,
    }
    return {"status": True, **file_model}


def _edge_store_file(file_payload: dict[str, Any], be_payload: dict[str, Any]) -> None:
    file_id = str(file_payload["id"])
    EDGE_FILE_STORE[file_id] = {
        "file": {k: v for k, v in file_payload.items() if k != "status"},
        "be": be_payload,
        "processing_status": "completed",
        "error": None,
        "updated_at": int(time.time()),
    }


def _edge_get_file_record(file_id: str) -> dict[str, Any] | None:
    return EDGE_FILE_STORE.get(file_id)


async def _edge_fetch_be_download(
    download_url: str, headers: dict[str, str]
) -> httpx.Response:
    if download_url.startswith("http://") or download_url.startswith("https://"):
        def _get_sync() -> httpx.Response:
            with httpx.Client(timeout=config.backend.timeout_seconds) as client:
                return client.get(download_url, headers=headers)

        return await asyncio.to_thread(_get_sync)

    normalized_path = download_url if download_url.startswith("/") else f"/{download_url}"
    return await backend_client.get(path=normalized_path, headers=headers)


async def _forward_openai_json_to_be(
    path: str,
    payload: Dict[str, Any],
    headers: dict[str, str],
    *,
    require_model: bool,
    force_non_stream: bool,
    error_message: str,
) -> JSONResponse:
    _normalize_openai_model(payload, require_model=require_model)
    if force_non_stream:
        payload["stream"] = False

    try:
        be_response = await backend_client.post_json(
            path=path,
            payload=payload,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": error_message, "error": str(exc)},
        ) from exc

    try:
        be_payload = be_response.json()
    except Exception:
        be_payload = {"raw_response": be_response.text}

    return JSONResponse(status_code=be_response.status_code, content=be_payload)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    payload = await request.json()
    body = _get_body(payload)
    headers = _bridge_headers_from_request(request)

    # Debug: remove if noisy
    print(
        f"proxy→be chat.completions model={body.get('model')} user={(body.get('user') or '')[:12]}",
        flush=True,
    )

    return await _forward_openai_json_to_be(
        path="/v1/chat/completions",
        payload=body,
        headers=headers,
        require_model=True,
        force_non_stream=True,
        error_message="Failed forwarding chat completion to BE",
    )


@app.post("/chat/completions")
async def chat_completions_alias(request: Request):
    """Compatibility alias without /v1 prefix."""
    return await chat_completions(request)


@app.post("/v1/completions")
async def completions(request: Request):
    payload = await request.json()
    body = _get_body(payload)
    headers = _bridge_headers_from_request(request)

    print(
        f"proxy→be completions model={body.get('model')} user={(body.get('user') or '')[:12]}",
        flush=True,
    )

    return await _forward_openai_json_to_be(
        path="/v1/completions",
        payload=body,
        headers=headers,
        require_model=True,
        force_non_stream=True,
        error_message="Failed forwarding completion to BE",
    )


@app.post("/completions")
async def completions_alias(request: Request):
    """Compatibility alias without /v1 prefix."""
    return await completions(request)


@app.post("/v1/responses")
async def responses(request: Request):
    payload = await request.json()
    body = _get_body(payload)
    headers = _bridge_headers_from_request(request)

    print(
        f"proxy→be responses model={body.get('model')} user={(body.get('user') or '')[:12]}",
        flush=True,
    )
    _normalize_openai_model(body, require_model=False)
    body["stream"] = False

    try:
        be_response = await backend_client.post_json(
            path="/v1/responses",
            payload=body,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "Failed forwarding response request to BE", "error": str(exc)},
        ) from exc

    try:
        be_payload = be_response.json()
    except Exception:
        be_payload = {"raw_response": be_response.text}

    # Some upstream deployments return 404 Not Found for /v1/responses.
    # In that case, fallback to chat.completions and translate the output shape.
    if be_response.status_code == 404 and _is_upstream_not_found(be_payload):
        fallback_payload = _build_chat_fallback_payload_from_responses(body)
        _normalize_openai_model(fallback_payload, require_model=True)
        fallback_payload["stream"] = False

        try:
            chat_response = await backend_client.post_json(
                path="/v1/chat/completions",
                payload=fallback_payload,
                headers=headers,
            )
        except httpx.HTTPError as exc:
            raise HTTPException(
                status_code=502,
                detail={
                    "message": "Failed forwarding /v1/responses fallback to chat.completions",
                    "error": str(exc),
                },
            ) from exc

        try:
            chat_payload = chat_response.json()
        except Exception:
            chat_payload = {"raw_response": chat_response.text}

        if chat_response.status_code >= 400 or not isinstance(chat_payload, dict):
            return JSONResponse(status_code=chat_response.status_code, content=chat_payload)

        translated = _chat_completion_to_responses_shape(fallback_payload, chat_payload)
        translated["fallback"] = {
            "active": True,
            "reason": "upstream_/v1/responses_not_available",
        }
        return JSONResponse(status_code=200, content=translated)

    return JSONResponse(status_code=be_response.status_code, content=be_payload)


@app.post("/responses")
async def responses_alias(request: Request):
    """Compatibility alias without /v1 prefix."""
    return await responses(request)


def _bridge_headers_from_request(request: Request) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name in ("authorization", "x-debug-user"):
        value = request.headers.get(name)
        if value:
            headers[name] = value
    return headers


# -------------------------
# Edge Gateway compatibility endpoints for Open WebUI files API
# -------------------------
@app.post("/api/v1/files")
@app.post("/api/v1/files/")
async def edge_upload_file(request: Request):
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(status_code=400, detail="Upload requires multipart/form-data")

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty multipart body")

    user_id = _edge_user_id_from_request(request)
    headers = _edge_backend_headers_from_request(request, user_id=user_id)

    try:
        be_response = await backend_client.upload_multipart_raw(
            body=body,
            content_type=content_type,
            headers=headers,
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "Failed forwarding edge upload to BE", "error": str(exc)},
        ) from exc

    try:
        be_payload = be_response.json()
    except Exception:
        be_payload = {"raw_response": be_response.text}

    if be_response.status_code >= 400 or not isinstance(be_payload, dict):
        return JSONResponse(status_code=be_response.status_code, content=be_payload)

    adapted_payload = _adapt_be_upload_to_box_shape(be_payload, user_id=user_id)
    _edge_store_file(adapted_payload, be_payload=be_payload)
    return JSONResponse(status_code=200, content=adapted_payload)


@app.get("/api/v1/files/{file_id}")
async def edge_get_file(file_id: str):
    record = _edge_get_file_record(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="Not Found")
    return JSONResponse(status_code=200, content=record["file"])


@app.get("/api/v1/files/{file_id}/process/status")
async def edge_get_file_process_status(file_id: str, stream: bool = False):
    record = _edge_get_file_record(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="Not Found")

    status_value = str(record.get("processing_status") or "completed")
    error_value = record.get("error")

    if stream:
        async def event_stream() -> Any:
            payload: dict[str, Any] = {"status": status_value}
            if status_value == "failed" and error_value:
                payload["error"] = error_value
            yield f"data: {json.dumps(payload)}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    return {"status": status_value}


@app.get("/api/v1/files/{file_id}/content")
async def edge_get_file_content(file_id: str, request: Request):
    record = _edge_get_file_record(file_id)
    if not record:
        raise HTTPException(status_code=404, detail="Not Found")

    be_payload = record.get("be", {})
    download_url = str(be_payload.get("download_url") or f"/api/v1/uploads/{file_id}/download")
    headers = _edge_backend_headers_from_request(request, user_id=str(record["file"]["user_id"]))

    try:
        upstream = await _edge_fetch_be_download(download_url=download_url, headers=headers)
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={"message": "Failed fetching file content from BE", "error": str(exc)},
        ) from exc

    media_type = upstream.headers.get("content-type", "application/octet-stream")
    response_headers: dict[str, str] = {}
    content_disposition = upstream.headers.get("content-disposition")
    if content_disposition:
        response_headers["content-disposition"] = content_disposition

    return Response(
        content=upstream.content,
        media_type=media_type,
        status_code=upstream.status_code,
        headers=response_headers,
    )


@app.get("/api/v1/files/{file_id}/content/html")
async def edge_get_file_content_html(file_id: str, request: Request):
    return await edge_get_file_content(file_id, request)


@app.post("/v1/uploads/bridge")
async def uploads_bridge_v1(request: Request):
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("multipart/form-data"):
        raise HTTPException(
            status_code=400, detail="Upload bridge requires multipart/form-data"
        )

    body = await request.body()
    if not body:
        raise HTTPException(status_code=400, detail="Empty multipart body")

    bridge_upload_id = uuid.uuid4().hex
    headers = _bridge_headers_from_request(request)

    try:
        be_response = await backend_client.upload_multipart_raw(
            body=body, content_type=content_type, headers=headers
        )
    except httpx.HTTPError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "message": "Failed forwarding upload to BE",
                "bridge_upload_id": bridge_upload_id,
                "error": str(exc),
            },
        ) from exc

    try:
        be_payload = be_response.json()
    except Exception:
        be_payload = {"raw_response": be_response.text}

    if isinstance(be_payload, dict):
        response_payload: Dict[str, Any] = {
            "bridge_upload_id": bridge_upload_id,
            **be_payload,
        }
    else:
        response_payload = {
            "bridge_upload_id": bridge_upload_id,
            "be_payload": be_payload,
        }

    return JSONResponse(status_code=be_response.status_code, content=response_payload)


@app.post("/uploads/bridge")
async def uploads_bridge(request: Request):
    """Compatibility alias without /v1 prefix."""
    return await uploads_bridge_v1(request)


# -------------------------
# Open WebUI Pipelines endpoints (NO /v1)
# -------------------------
@app.get("/pipelines")
async def pipelines() -> Dict[str, Any]:
    return {"data": [_serialize_pipeline()]}


@app.post("/pipelines/add")
async def pipelines_add():
    raise HTTPException(
        status_code=405, detail="Remote pipeline download not supported")


@app.post("/pipelines/upload")
async def pipelines_upload(request: Request):
    if not request.headers.get("content-type", "").startswith("multipart/form-data"):
        raise HTTPException(
            status_code=400, detail="Upload requires multipart/form-data")

    upload_dir = Path(config.pipeline.__dict__.get(
        "upload_dir", "pipelines-uploaded"))
    upload_dir.mkdir(parents=True, exist_ok=True)

    form = await request.form()
    file = form.get("file")
    if file is None:
        raise HTTPException(
            status_code=400, detail="Missing file in form data")

    filename = Path(file.filename or "pipeline.py").name
    target_path = (upload_dir / filename).resolve()

    if not target_path.suffix.endswith(".py"):
        raise HTTPException(
            status_code=400, detail="Only .py files are allowed")

    with target_path.open("wb") as dest:
        dest.write(await file.read())

    return {"data": {"id": config.pipeline.id, "filename": filename, "path": str(target_path)}}


def _ensure_pipeline(pipeline_id: str) -> None:
    if pipeline_id != config.pipeline.id:
        raise HTTPException(status_code=404, detail="Pipeline not found")


@app.post("/{pipeline_id}/filter/inlet")
async def pipeline_inlet(pipeline_id: str, request: Request):
    _ensure_pipeline(pipeline_id)

    payload = await request.json()
    body = _get_body(payload)

    chat_id = _get_chat_id(payload, body)
    if config.pipeline.enforce_user and chat_id:
        body["user"] = _session_key(_get_user_id(payload), chat_id)

    enforce_prefix = config.pipeline.enforce_prefix
    if enforce_prefix:
        model_id = body.get("model")
        if isinstance(model_id, str) and not model_id.startswith(enforce_prefix):
            body["model"] = f"{enforce_prefix}{model_id}"

    return body


@app.post("/{pipeline_id}/filter/outlet")
async def pipeline_outlet(pipeline_id: str, request: Request):
    _ensure_pipeline(pipeline_id)
    payload = await request.json()
    return payload.get("body", payload)


@app.get("/{pipeline_id}/valves")
async def pipeline_valves(pipeline_id: str):
    _ensure_pipeline(pipeline_id)
    cfg = _load_valves_config()
    values = cfg.get("values")
    if not isinstance(values, dict):
        values = {}
    return values


@app.get("/{pipeline_id}/valves/spec")
async def pipeline_valves_spec(pipeline_id: str):
    _ensure_pipeline(pipeline_id)
    cfg = _load_valves_config()
    spec = cfg.get("schema")
    if not isinstance(spec, dict) or not spec:
        spec = {
            "fields": [
                {
                    "id": "sessionKeyFormat",
                    "label": "Formato session key",
                    "type": "text",
                    "default": "sha256(user_id:chat_id)[:64]",
                    "editable": False,
                }
            ]
        }
    return spec


@app.post("/{pipeline_id}/valves/update")
async def pipeline_valves_update(pipeline_id: str, request: Request):
    _ensure_pipeline(pipeline_id)

    cfg = _load_valves_config()
    values = cfg.get("values")
    if not isinstance(values, dict):
        values = {}

    payload = await request.json()
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Invalid payload")

    values.update(payload)
    cfg["values"] = values
    _save_valves_config(cfg)
    return values


# -------------------------
# /v1 aliases for Pipelines (Open WebUI expects these when Base URL ends with /v1)
# -------------------------
@app.get("/v1/pipelines")
async def pipelines_v1() -> Dict[str, Any]:
    return await pipelines()


@app.post("/v1/pipelines/add")
async def pipelines_add_v1():
    return await pipelines_add()


@app.post("/v1/pipelines/upload")
async def pipelines_upload_v1(request: Request):
    return await pipelines_upload(request)


@app.post("/v1/{pipeline_id}/filter/inlet")
async def pipeline_inlet_v1(pipeline_id: str, request: Request):
    return await pipeline_inlet(pipeline_id, request)


@app.post("/v1/{pipeline_id}/filter/outlet")
async def pipeline_outlet_v1(pipeline_id: str, request: Request):
    return await pipeline_outlet(pipeline_id, request)


@app.get("/v1/{pipeline_id}/valves")
async def pipeline_valves_v1(pipeline_id: str):
    return await pipeline_valves(pipeline_id)


@app.get("/v1/{pipeline_id}/valves/spec")
async def pipeline_valves_spec_v1(pipeline_id: str):
    return await pipeline_valves_spec(pipeline_id)


@app.post("/v1/{pipeline_id}/valves/update")
async def pipeline_valves_update_v1(pipeline_id: str, request: Request):
    return await pipeline_valves_update(pipeline_id, request)
