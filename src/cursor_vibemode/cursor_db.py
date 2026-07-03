from __future__ import annotations

import json
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .paths import (
    APP_USER_KEY,
    MARKER_KEY,
    MODEL_LABELS,
    OPENAI_KEY_STORAGE,
    VIBEMODE_MODELS,
)


@dataclass(frozen=True)
class CursorStatus:
    db_path: Path
    has_item_table: bool
    has_key: bool
    use_openai_key: bool | None
    base_url: str
    composer_model: str
    registered_models: list[str]


def backup_database(db_path: Path) -> list[Path]:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups: list[Path] = []
    for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        if not path.exists():
            continue
        backup = path.with_name(f"{path.name}.bak-{stamp}")
        shutil.copy2(path, backup)
        try:
            os.chmod(backup, 0o600)
        except OSError:
            pass
        backups.append(backup)
    cleanup_old_backups(db_path)
    return backups


def cleanup_old_backups(db_path: Path, keep: int = 3) -> None:
    for path in (db_path, Path(str(db_path) + "-wal"), Path(str(db_path) + "-shm")):
        pattern = f"{path.name}.bak-*"
        backups = sorted(path.parent.glob(pattern), key=lambda item: item.name, reverse=True)
        for old_backup in backups[keep:]:
            try:
                old_backup.unlink()
            except OSError:
                pass


def connect(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path), timeout=15)


def has_item_table(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ItemTable'"
    ).fetchone()
    return bool(row)


def get_value(conn: sqlite3.Connection, key: str) -> str:
    row = conn.execute("SELECT value FROM ItemTable WHERE key=?", (key,)).fetchone()
    if not row:
        return ""
    value = row[0]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def set_value(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO ItemTable (key, value) VALUES (?, ?)",
        (key, value),
    )


def read_json_value(conn: sqlite3.Connection, key: str) -> dict[str, Any]:
    raw = get_value(conn, key)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def write_json_value(conn: sqlite3.Connection, key: str, data: dict[str, Any]) -> None:
    set_value(conn, key, json.dumps(data, ensure_ascii=False, separators=(",", ":")))


def touch_marker(conn: sqlite3.Connection, keys: list[str]) -> None:
    marker = read_json_value(conn, MARKER_KEY)
    changed = False
    for key in keys:
        if key not in marker:
            marker[key] = 0
            changed = True
    if changed:
        write_json_value(conn, MARKER_KEY, marker)


def display_name(model_id: str) -> str:
    return MODEL_LABELS.get(model_id, model_id)


def model_variant(model_id: str) -> dict[str, Any]:
    label = display_name(model_id)
    return {
        "parameterValues": [],
        "displayName": label,
        "isMaxMode": False,
        "isDefaultMaxConfig": True,
        "isDefaultNonMaxConfig": True,
        "displayNameOutsidePicker": label,
        "variantStringRepresentation": f"{model_id}[]",
        "legacySlug": model_id,
    }


def model_catalog_entry(model_id: str, template: dict[str, Any] | None) -> dict[str, Any]:
    entry = dict(template or {})
    entry.update(
        {
            "name": model_id,
            "serverModelName": model_id,
            "clientDisplayName": display_name(model_id),
            "inputboxShortModelName": display_name(model_id),
            "displayNameOutsidePicker": display_name(model_id),
            "variants": [model_variant(model_id)],
            "vendorName": "openai",
            "vendor": {"id": 0, "displayName": "OpenAI"},
            "isUserAdded": True,
            "defaultOn": False,
            "parameterDefinitions": entry.get("parameterDefinitions") or [],
            "legacySlugs": entry.get("legacySlugs") or [],
            "idAliases": entry.get("idAliases") or [],
            "supportsAgent": True,
            "supportsPlanMode": True,
            "supportsImages": True,
            "supportsThinking": True,
            "supportsMaxMode": True,
            "supportsNonMaxMode": True,
        }
    )
    return entry


def register_models(data: dict[str, Any], model_ids: list[str]) -> None:
    ai_settings = data.setdefault("aiSettings", {})
    for key in ("userAddedModels", "modelOverrideEnabled"):
        current = list(ai_settings.get(key) or [])
        for model_id in model_ids:
            if model_id not in current:
                current.append(model_id)
        ai_settings[key] = current

    catalog = list(data.get("availableDefaultModels2") or [])
    by_name = {m.get("name"): m for m in catalog if isinstance(m, dict)}
    template = next((m for m in catalog if isinstance(m, dict)), None)
    for model_id in model_ids:
        by_name[model_id] = model_catalog_entry(model_id, by_name.get(model_id) or template)
    data["availableDefaultModels2"] = list(by_name.values())


def set_default_model(data: dict[str, Any], model_id: str) -> None:
    ai_settings = data.setdefault("aiSettings", {})
    selected = [{"modelId": model_id, "parameters": []}]
    model_config = ai_settings.get("modelConfig")
    if isinstance(model_config, dict):
        for item in model_config.values():
            if isinstance(item, dict):
                item["modelName"] = model_id
                item["selectedModels"] = selected
    ai_settings["composerModel"] = model_id
    ai_settings["cmdKModel"] = model_id
    ai_settings["backgroundComposerModel"] = model_id
    data["composerModel"] = model_id


def patch_application_user(
    data: dict[str, Any],
    *,
    base_url: str,
    model_id: str,
    model_ids: list[str],
) -> dict[str, Any]:
    data["openAIBaseUrl"] = base_url.rstrip("/")
    data["useOpenAIKey"] = True
    register_models(data, model_ids)
    set_default_model(data, model_id)
    return data


def read_status(db_path: Path) -> CursorStatus:
    if not db_path.is_file():
        return CursorStatus(db_path, False, False, None, "", "", [])
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            return CursorStatus(db_path, False, False, None, "", "", [])
        app_user = read_json_value(conn, APP_USER_KEY)
        catalog = app_user.get("availableDefaultModels2") or []
        models = [m.get("name") for m in catalog if isinstance(m, dict) and m.get("name")]
        return CursorStatus(
            db_path=db_path,
            has_item_table=True,
            has_key=bool(get_value(conn, OPENAI_KEY_STORAGE)),
            use_openai_key=app_user.get("useOpenAIKey"),
            base_url=str(app_user.get("openAIBaseUrl") or ""),
            composer_model=str(app_user.get("composerModel") or ""),
            registered_models=models,
        )


def read_openai_key(db_path: Path) -> str:
    if not db_path.is_file():
        return ""
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            return ""
        return get_value(conn, OPENAI_KEY_STORAGE).strip()


def apply_setup(
    db_path: Path,
    *,
    api_key: str,
    base_url: str,
    model_id: str,
    model_ids: list[str] | None = None,
    backup: bool = True,
) -> list[Path]:
    backups = backup_database(db_path) if backup else []
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            raise RuntimeError(f"ItemTable not found in {db_path}")
        app_user = read_json_value(conn, APP_USER_KEY)
        models = model_ids or list(VIBEMODE_MODELS)
        if model_id not in models:
            models.insert(0, model_id)
        app_user = patch_application_user(
            app_user,
            base_url=base_url,
            model_id=model_id,
            model_ids=models,
        )
        write_json_value(conn, APP_USER_KEY, app_user)
        set_value(conn, OPENAI_KEY_STORAGE, api_key)
        touch_marker(conn, [APP_USER_KEY, OPENAI_KEY_STORAGE])
        conn.commit()
    return backups


def set_openai_enabled(db_path: Path, enabled: bool, *, backup: bool = True) -> list[Path]:
    backups = backup_database(db_path) if backup else []
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            raise RuntimeError(f"ItemTable not found in {db_path}")
        app_user = read_json_value(conn, APP_USER_KEY)
        app_user["useOpenAIKey"] = enabled
        write_json_value(conn, APP_USER_KEY, app_user)
        touch_marker(conn, [APP_USER_KEY])
        conn.commit()
    return backups


def remove_openai_key(db_path: Path, *, backup: bool = True) -> list[Path]:
    backups = set_openai_enabled(db_path, False, backup=backup)
    with closing(connect(db_path)) as conn:
        conn.execute("DELETE FROM ItemTable WHERE key=?", (OPENAI_KEY_STORAGE,))
        conn.commit()
    return backups
