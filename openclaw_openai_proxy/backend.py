from __future__ import annotations

import asyncio

import httpx

from .config import AppConfig

class BackendClient:
    """HTTP client that forwards upload traffic to the OpenClaw BFF."""

    def __init__(self, config: AppConfig):
        self._config = config
        self._timeout = config.backend.timeout_seconds

    @property
    def base_url(self) -> str:
        return str(self._config.backend.base_url).rstrip("/")

    async def post_json(
        self,
        path: str,
        payload: dict,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        target_url = f"{self.base_url}{path}"
        resolved_headers = dict(headers or {})

        def _post_sync() -> httpx.Response:
            with httpx.Client(timeout=self._timeout) as client:
                return client.post(
                    target_url,
                    json=payload,
                    headers=resolved_headers,
                )

        return await asyncio.to_thread(_post_sync)

    async def get(
        self,
        path: str,
        headers: dict[str, str] | None = None,
        params: dict[str, str | int | bool] | None = None,
    ) -> httpx.Response:
        target_url = f"{self.base_url}{path}"
        resolved_headers = dict(headers or {})
        resolved_params = dict(params or {})

        def _get_sync() -> httpx.Response:
            with httpx.Client(timeout=self._timeout) as client:
                return client.get(
                    target_url,
                    headers=resolved_headers,
                    params=resolved_params,
                )

        return await asyncio.to_thread(_get_sync)

    async def upload_multipart_raw(
        self,
        body: bytes,
        content_type: str,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        target_url = f"{self.base_url}/api/v1/uploads"
        resolved_headers = dict(headers or {})
        resolved_headers["content-type"] = content_type

        # Keep the original multipart body and boundary untouched.
        def _post_sync() -> httpx.Response:
            with httpx.Client(timeout=self._timeout) as client:
                return client.post(
                    target_url,
                    content=body,
                    headers=resolved_headers,
                )

        return await asyncio.to_thread(_post_sync)

    async def close(self) -> None:
        return None
