from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EndpointCheck:
    model_id: str
    endpoint: str
    ok: bool
    detail: str


def sanitize_api_text(text: str, key: str) -> str:
    safe = text.replace(key, "[redacted]") if key else text
    if "Bearer " in safe:
        safe = safe.split("Bearer ")[0] + "Bearer [redacted]"
    return safe[:500]


def api_json(
    base_url: str,
    api_key: str,
    path: str,
    *,
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    url = base_url.rstrip("/") + path
    data = None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
    }
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        detail = sanitize_api_text(body, api_key)
        raise RuntimeError(f"HTTP {error.code} | {detail}") from error
    except urllib.error.URLError as error:
        detail = sanitize_api_text(str(error.reason), api_key)
        raise RuntimeError(detail) from error

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{path} succeeded, but response was not JSON") from error
    return payload if isinstance(payload, dict) else {}


def check_models(base_url: str, api_key: str, timeout: int = 30) -> list[str]:
    payload = api_json(base_url, api_key, "/models", timeout=timeout)
    models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    return [model for model in models if model]


def endpoint_for_model(model_id: str) -> str:
    lower = model_id.lower()
    return "responses" if lower.startswith("gpt-") else "chat/completions"


def endpoint_path(endpoint: str) -> str:
    return "/responses" if endpoint == "responses" else "/chat/completions"


def endpoint_payload(model_id: str, endpoint: str) -> dict[str, Any]:
    if endpoint == "responses":
        return {
            "model": model_id,
            "input": "Reply with ok.",
            "max_output_tokens": 8,
            "stream": False,
        }
    return {
        "model": model_id,
        "messages": [{"role": "user", "content": "Reply with ok."}],
        "max_tokens": 8,
        "stream": False,
    }


def check_model_endpoint(
    base_url: str,
    api_key: str,
    model_id: str,
    *,
    timeout: int = 45,
) -> EndpointCheck:
    endpoint = endpoint_for_model(model_id)
    try:
        api_json(
            base_url,
            api_key,
            endpoint_path(endpoint),
            payload=endpoint_payload(model_id, endpoint),
            timeout=timeout,
        )
    except RuntimeError as error:
        return EndpointCheck(model_id, endpoint, False, str(error))
    return EndpointCheck(model_id, endpoint, True, "ok")


def check_model_endpoints(
    base_url: str,
    api_key: str,
    model_ids: list[str],
    *,
    timeout: int = 45,
) -> list[EndpointCheck]:
    return [
        check_model_endpoint(base_url, api_key, model_id, timeout=timeout)
        for model_id in model_ids
    ]
