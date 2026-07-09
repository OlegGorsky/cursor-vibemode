from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .paths import (
    VIBEMODE_MESSAGES_MODELS,
    VIBEMODE_MODELS,
    VIBEMODE_RESPONSE_MODELS,
)


MODEL_CONTEXT_WINDOWS = {
    "deepseek-v4-flash": 1_000_000,
    "deepseek-v4-pro": 1_000_000,
    "glm-5.1": 203_000,
    "glm-5.2": 203_000,
    "gpt-5.4-mini": 272_000,
    "gpt-5.5": 272_000,
    "gpt-5.6-luna": 128_000,
    "gpt-5.6-sol": 272_000,
    "gpt-5.6-terra": 272_000,
    "kimi-k2.6": 262_000,
    "mimo-v2.5": 1_000_000,
    "mimo-v2.5-pro": 1_000_000,
    "minimax-m3": 1_000_000,
    "qwen3.7-max": 1_000_000,
    "qwen3.7-plus": 1_000_000,
    "vibe-lite-1.5": 1_000_000,
}


class CatalogCache:
    def __init__(self, path: Path, ttl_seconds: int) -> None:
        self.path = path
        self.ttl_seconds = ttl_seconds
        self.value: dict[str, Any] | None = None
        self.loaded_at = 0.0

    def get(self) -> dict[str, Any] | None:
        if self.value and time.time() - self.loaded_at < self.ttl_seconds:
            return self.value
        cached = self.read_disk()
        if cached:
            self.value = cached
            self.loaded_at = time.time()
            return cached
        return None

    def set(self, value: dict[str, Any]) -> None:
        self.value = value
        self.loaded_at = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stored = {"_cached_at": self.loaded_at, "payload": value}
        self.path.write_text(json.dumps(stored, ensure_ascii=False), encoding="utf-8")

    def read_disk(self, *, allow_stale: bool = False) -> dict[str, Any] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(data, dict):
            return None
        cached_at = data.get("_cached_at")
        if not isinstance(cached_at, (int, float)):
            return None
        if not allow_stale and time.time() - cached_at > self.ttl_seconds:
            return None
        payload = data.get("payload")
        return payload if isinstance(payload, dict) else None


def enrich_models(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("data")
    if not isinstance(items, list):
        return payload
    enriched = dict(payload)
    enriched["data"] = [enrich_model(item) for item in items]
    return enriched


def enrich_model(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    model_id = str(item.get("id") or "")
    source_caps = item.get("capabilities")
    cap_names = source_caps if isinstance(source_caps, list) else []
    enriched = dict(item)
    enriched["api_types"] = api_types_for_model(model_id)
    enriched["capabilities"] = {
        "context_length": context_window(model_id, item),
        "supports_streaming": True,
        "supports_tool_use": "tools" in cap_names,
        "supports_vision": "vision" in cap_names,
        "supports_reasoning": "reasoning" in cap_names,
    }
    return enriched


def api_types_for_model(model_id: str) -> list[str]:
    lower = model_id.lower()
    if lower in VIBEMODE_MESSAGES_MODELS:
        return ["anthropic_messages"]
    if lower in VIBEMODE_RESPONSE_MODELS or lower.startswith("gpt-"):
        return ["responses"]
    return ["chat_completions"]


def context_window(model_id: str, item: dict[str, Any]) -> int:
    raw = item.get("context_window") or item.get("context_length")
    if isinstance(raw, int):
        return raw
    return MODEL_CONTEXT_WINDOWS.get(model_id.lower(), 0)


def fallback_catalog() -> dict[str, Any]:
    return enrich_models(
        {"object": "list", "data": [fallback_model(model) for model in VIBEMODE_MODELS]}
    )


def fallback_model(model_id: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "object": "model",
        "created": 0,
        "owned_by": "vibemode",
        "context_window": MODEL_CONTEXT_WINDOWS.get(model_id, 0),
        "capabilities": fallback_capabilities(model_id),
    }


def fallback_capabilities(model_id: str) -> list[str]:
    if model_id in {
        "gpt-5.4-mini",
        "gpt-5.5",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "minimax-m3",
    }:
        return ["chat", "vision", "reasoning"]
    if model_id == "gpt-5.6-luna":
        return ["chat", "reasoning"]
    if model_id.startswith("qwen"):
        return ["chat", "reasoning", "tools"]
    if model_id.startswith(("deepseek", "glm", "mimo")):
        return ["chat", "reasoning", "tools"]
    return ["chat"]
