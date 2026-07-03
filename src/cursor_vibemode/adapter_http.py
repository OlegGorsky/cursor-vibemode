from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from .api import sanitize_api_text


def proxy_path(path: str) -> str:
    parsed = urlparse(path)
    clean = parsed.path
    if clean.startswith("/v1/"):
        clean = clean[3:]
    elif clean == "/v1":
        clean = ""
    query = f"?{parsed.query}" if parsed.query else ""
    return clean + query


def upstream_headers(headers: Any, path: str, configured_api_key: str = "") -> dict[str, str]:
    result = {
        "Accept": header_value(headers, "accept") or "application/json",
        "User-Agent": upstream_user_agent(header_value(headers, "user-agent")),
    }
    authorization = header_value(headers, "authorization")
    inbound_api_key = header_value(headers, "x-api-key")
    api_key = select_api_key(configured_api_key, authorization, inbound_api_key)
    if api_key:
        result["Authorization"] = f"Bearer {api_key}"
    elif authorization:
        result["Authorization"] = authorization
    content_type = header_value(headers, "content-type")
    if content_type:
        result["Content-Type"] = content_type
    if path.startswith("/messages"):
        if api_key:
            result["x-api-key"] = api_key
            result["Authorization"] = f"Bearer {api_key}"
        result["anthropic-version"] = header_value(headers, "anthropic-version") or "2023-06-01"
        beta = header_value(headers, "anthropic-beta")
        if beta:
            result["anthropic-beta"] = beta
    return result


def header_value(headers: Any, name: str) -> str:
    value = headers.get(name)
    if value:
        return str(value)
    title = "-".join(part.capitalize() for part in name.split("-"))
    value = headers.get(title)
    if value:
        return str(value)
    lower = name.lower()
    for key, item in getattr(headers, "items", lambda: [])():
        if str(key).lower() == lower:
            return str(item)
    return ""


def upstream_user_agent(value: str) -> str:
    clean = value.strip()
    if not clean or clean.lower().startswith("python-urllib"):
        return "Mozilla/5.0 cursor-vibemode/0.1"
    return clean


def select_api_key(configured: str, authorization: str, x_api_key: str) -> str:
    if looks_like_vibemode_key(configured):
        return configured.strip()
    bearer = bearer_token(authorization)
    if looks_like_vibemode_key(bearer):
        return bearer
    if looks_like_vibemode_key(x_api_key):
        return x_api_key.strip()
    return bearer or x_api_key.strip()


def bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix) :].strip() if value.startswith(prefix) else ""


def looks_like_vibemode_key(value: str) -> bool:
    clean = value.strip()
    return clean.startswith(("sk-", "sk_"))


def upstream_error_message(body: bytes) -> str:
    text = body.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return sanitize_api_text(text, "")
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return sanitize_api_text(error["message"], "")
        if isinstance(payload.get("message"), str):
            return sanitize_api_text(payload["message"], "")
    return sanitize_api_text(text, "")


def rewrite_messages_event(event: bytes) -> bytes:
    if b"event: error" not in event or b'{"error"' not in event:
        return event
    message = upstream_error_message(event_data(event))
    body = json.dumps(
        {"type": "error", "error": {"type": "api_error", "message": message}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"event: error\ndata: {body}\n\n".encode("utf-8")


def event_data(event: bytes) -> bytes:
    lines = []
    for raw in event.splitlines():
        if raw.startswith(b"data:"):
            lines.append(raw[5:].strip())
    return b"\n".join(lines)
