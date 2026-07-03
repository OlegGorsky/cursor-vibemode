from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .adapter_http import (
    proxy_path,
    rewrite_messages_event,
    upstream_error_message,
    upstream_headers,
)
from .adapter_models import CatalogCache, enrich_models, fallback_catalog
from .api import sanitize_api_text
from .paths import (
    ADAPTER_VERSION,
    adapter_cache_path,
    adapter_config_path,
)


@dataclass(frozen=True)
class AdapterConfig:
    upstream_base_url: str
    host: str = "127.0.0.1"
    port: int = 17654
    cache_ttl_seconds: int = 300
    api_key: str = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}/v1"


class VibemodeAdapterHandler(BaseHTTPRequestHandler):
    server_version = "CursorVibemodeAdapter/1"

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/v1/cursor-vibemode/health":
            self.write_json(
                {"ok": True, "base_url": self.config.base_url, "version": ADAPTER_VERSION}
            )
            return
        if self.path.rstrip("/") == "/v1/models":
            self.handle_models()
            return
        self.proxy()

    def do_POST(self) -> None:
        self.proxy()

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "authorization,content-type,x-api-key")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.end_headers()

    @property
    def config(self) -> AdapterConfig:
        try:
            return load_config()
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            return self.server.config  # type: ignore[attr-defined]

    @property
    def cache(self) -> CatalogCache:
        return self.server.cache  # type: ignore[attr-defined]

    def handle_models(self) -> None:
        cached = self.cache.get()
        if cached:
            self.write_json(cached)
            return
        try:
            payload = self.fetch_upstream_json("/models")
        except RuntimeError as error:
            fallback = self.cache.read_disk(allow_stale=True) or fallback_catalog()
            self.cache.set(fallback)
            self.write_json(fallback)
            return
        enriched = enrich_models(payload)
        self.cache.set(enriched)
        self.write_json(enriched)

    def proxy(self) -> None:
        self.stream_upstream(proxy_path(self.path), self.read_body())

    def stream_upstream(self, path: str, body: bytes | None) -> None:
        url = self.config.upstream_base_url.rstrip("/") + path
        headers = upstream_headers(self.headers, path, self.config.api_key)
        method = "POST" if body is not None else "GET"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                self.write_upstream_headers(response.status, dict(response.headers))
                if path.startswith("/messages"):
                    self.stream_messages_response(response)
                else:
                    self.stream_raw_response(response)
        except urllib.error.HTTPError as error:
            body_bytes = error.read()
            if path.startswith("/messages"):
                self.write_anthropic_error(error.code, body_bytes)
                return
            self.write_upstream_headers(error.code, dict(error.headers), len(body_bytes))
            try:
                self.wfile.write(body_bytes)
            except (BrokenPipeError, ConnectionResetError):
                return
        except urllib.error.URLError as error:
            self.write_error(502, sanitize_api_text(str(error.reason), ""))

    def write_upstream_headers(
        self,
        status: int,
        headers: dict[str, str],
        content_length: int | None = None,
    ) -> None:
        self.send_response(status)
        for key, value in headers.items():
            if key.lower() in {"connection", "content-length", "transfer-encoding"}:
                continue
            self.send_header(key, value)
        if content_length is not None:
            self.send_header("Content-Length", str(content_length))
        self.end_headers()

    def stream_raw_response(self, response) -> None:
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            if not self.write_bytes(chunk):
                return

    def stream_messages_response(self, response) -> None:
        pending = b""
        while True:
            chunk = response.read(8192)
            if not chunk:
                break
            pending += chunk
            parts = pending.split(b"\n\n")
            pending = parts.pop()
            for part in parts:
                if not self.write_bytes(rewrite_messages_event(part + b"\n\n")):
                    return
        if pending:
            self.write_bytes(rewrite_messages_event(pending))

    def write_bytes(self, chunk: bytes) -> bool:
        try:
            self.wfile.write(chunk)
            self.wfile.flush()
            return True
        except (BrokenPipeError, ConnectionResetError):
            return False

    def fetch_upstream_json(self, path: str) -> dict[str, Any]:
        response = self.fetch_upstream_raw(path)
        if response.status >= 400:
            body = response.body.decode("utf-8", errors="replace")
            raise RuntimeError(f"upstream HTTP {response.status}: {sanitize_api_text(body, '')}")
        try:
            payload = json.loads(response.body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError as error:
            raise RuntimeError("upstream returned non-JSON models response") from error
        return payload if isinstance(payload, dict) else {}

    def fetch_upstream_raw(self, path: str, body: bytes | None = None) -> UpstreamResponse:
        url = self.config.upstream_base_url.rstrip("/") + path
        headers = upstream_headers(self.headers, path, self.config.api_key)
        method = "POST" if body is not None else "GET"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return UpstreamResponse(response.status, dict(response.headers), response.read())
        except urllib.error.HTTPError as error:
            return UpstreamResponse(error.code, dict(error.headers), error.read())
        except urllib.error.URLError as error:
            raise RuntimeError(sanitize_api_text(str(error.reason), "")) from error

    def read_body(self) -> bytes | None:
        length = int(self.headers.get("content-length") or "0")
        return self.rfile.read(length) if length else b""

    def write_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def write_error(self, status: int, message: str) -> None:
        self.write_json({"error": {"message": message, "type": "adapter_error"}}, status)

    def write_anthropic_error(self, status: int, body: bytes) -> None:
        message = upstream_error_message(body)
        error_type = "authentication_error" if status in {401, 403} else "api_error"
        self.write_json(
            {"type": "error", "error": {"type": error_type, "message": message}},
            status,
        )

    def log_message(self, format: str, *args: object) -> None:
        return


@dataclass(frozen=True)
class UpstreamResponse:
    status: int
    headers: dict[str, str]
    body: bytes


def load_config() -> AdapterConfig:
    data = json.loads(adapter_config_path().read_text(encoding="utf-8"))
    return AdapterConfig(
        upstream_base_url=str(data["upstream_base_url"]).rstrip("/"),
        host=str(data.get("host") or "127.0.0.1"),
        port=int(data.get("port") or 17654),
        cache_ttl_seconds=int(data.get("cache_ttl_seconds") or 300),
        api_key=str(data.get("api_key") or ""),
    )


def run() -> None:
    config = load_config()
    server = ThreadingHTTPServer((config.host, config.port), VibemodeAdapterHandler)
    server.config = config  # type: ignore[attr-defined]
    server.cache = CatalogCache(  # type: ignore[attr-defined]
        adapter_cache_path(),
        config.cache_ttl_seconds,
    )
    server.serve_forever()
