from __future__ import annotations

import json
import urllib.error
import urllib.request


def sanitize_api_text(text: str, key: str) -> str:
    safe = text.replace(key, "[redacted]") if key else text
    if "Bearer " in safe:
        safe = safe.split("Bearer ")[0] + "Bearer [redacted]"
    return safe[:500]


def check_models(base_url: str, api_key: str, timeout: int = 30) -> list[str]:
    url = base_url.rstrip("/") + "/models"
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        detail = sanitize_api_text(body, api_key)
        raise RuntimeError(f"API check failed: HTTP {error.code} | {detail}") from error
    except urllib.error.URLError as error:
        detail = sanitize_api_text(str(error.reason), api_key)
        raise RuntimeError(f"API check failed: {detail}") from error

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as error:
        raise RuntimeError("API check succeeded, but /models was not JSON") from error
    models = [item.get("id") for item in payload.get("data", []) if isinstance(item, dict)]
    return [model for model in models if model]
