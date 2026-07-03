from __future__ import annotations

from typing import Any

from .paths import MODEL_LABELS


CURSOR_MODEL_PREFIX = "vibemode-"


def cursor_model_id(provider_model_id: str) -> str:
    return f"{CURSOR_MODEL_PREFIX}{provider_model_id}"


def provider_model_id(model_id: str) -> str:
    if model_id.startswith(CURSOR_MODEL_PREFIX):
        return model_id[len(CURSOR_MODEL_PREFIX) :]
    return model_id


def is_cursor_vibemode_model(model_id: object) -> bool:
    return isinstance(model_id, str) and model_id.startswith(CURSOR_MODEL_PREFIX)


def display_name(provider_model_id: str) -> str:
    return MODEL_LABELS.get(
        provider_model_id,
        f"{humanize_model_id(provider_model_id)} [Vibemode]",
    )


def humanize_model_id(model_id: str) -> str:
    words = []
    known = {
        "ai": "AI",
        "api": "API",
        "claude": "Claude",
        "codex": "Codex",
        "deepseek": "DeepSeek",
        "flash": "Flash",
        "gemini": "Gemini",
        "glm": "GLM",
        "gpt": "GPT",
        "k2": "K2",
        "kimi": "Kimi",
        "lite": "Lite",
        "max": "Max",
        "mini": "Mini",
        "minimax": "MiniMax",
        "mistral": "Mistral",
        "plus": "Plus",
        "pro": "Pro",
        "qwen": "Qwen",
        "vibe": "Vibe",
    }
    for part in model_id.replace("_", "-").split("-"):
        fallback = part.upper() if part.isdigit() else part.title()
        words.append(known.get(part.lower(), fallback))
    return " ".join(words)


def model_catalog_entry(
    provider_id: str,
    template: dict[str, Any] | None,
) -> dict[str, Any]:
    entry = dict(template or {})
    label = display_name(provider_id)
    entry.update(
        {
            "name": provider_id,
            "serverModelName": provider_id,
            "clientDisplayName": label,
            "inputboxShortModelName": label,
            "displayNameOutsidePicker": label,
            "variants": [],
            "vendorName": "openai",
            "vendor": {"id": 0, "displayName": "OpenAI"},
            "isUserAdded": True,
            "defaultOn": False,
            "parameterDefinitions": [],
            "legacySlugs": [],
            "idAliases": [],
            "cloudAgentEffortModes": [],
            "degradationStatus": 0,
            "isRecommendedForBackgroundComposer": False,
            "namedModelSectionIndex": 1,
            "supportsAgent": True,
            "supportsPlanMode": True,
            "supportsImages": True,
            "supportsThinking": True,
            "supportsMaxMode": True,
            "supportsNonMaxMode": True,
            "supportsSandboxing": True,
        }
    )
    return entry


def catalog_provider_model_id(entry: dict[str, Any]) -> str:
    name = entry.get("name")
    if not isinstance(name, str):
        return ""
    if not is_cursor_vibemode_model(name):
        label = " ".join(
            str(entry.get(key) or "")
            for key in (
                "clientDisplayName",
                "inputboxShortModelName",
                "displayNameOutsidePicker",
            )
        )
        if entry.get("isUserAdded") is not True and "Vibemode" not in label:
            return ""
        server_name = entry.get("serverModelName")
        model_id = str(server_name or name)
        return provider_model_id(model_id)
    server_name = entry.get("serverModelName")
    return str(server_name or provider_model_id(name))
