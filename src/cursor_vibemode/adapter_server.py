from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

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
        headers = upstream_headers(self.headers, path)
        method = "POST" if body is not None else "GET"
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                self.write_upstream_headers(response.status, dict(response.headers))
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return
        except urllib.error.HTTPError as error:
            body_bytes = error.read()
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
        headers = upstream_headers(self.headers, path)
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


def proxy_path(path: str) -> str:
    parsed = urlparse(path)
    clean = parsed.path
    if clean.startswith("/v1/"):
        clean = clean[3:]
    elif clean == "/v1":
        clean = ""
    query = f"?{parsed.query}" if parsed.query else ""
    return clean + query


def upstream_headers(headers: Any, path: str) -> dict[str, str]:
    result = {
        "Accept": headers.get("accept") or "application/json",
        "User-Agent": headers.get("user-agent") or "CursorVibemodeAdapter/1",
    }
    authorization = headers.get("authorization")
    inbound_api_key = headers.get("x-api-key")
    if authorization:
        result["Authorization"] = authorization
    content_type = headers.get("content-type")
    if content_type:
        result["Content-Type"] = content_type
    if path.startswith("/messages"):
        api_key = inbound_api_key or bearer_token(authorization or "")
        if api_key:
            result["x-api-key"] = api_key
            result.setdefault("Authorization", f"Bearer {api_key}")
        result["anthropic-version"] = headers.get("anthropic-version") or "2023-06-01"
        beta = headers.get("anthropic-beta")
        if beta:
            result["anthropic-beta"] = beta
    return result


def bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix) :].strip() if value.startswith(prefix) else ""
