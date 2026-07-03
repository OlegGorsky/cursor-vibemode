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

from .models import (
    catalog_provider_model_id,
    cursor_model_id,
    is_cursor_vibemode_model,
    model_catalog_entry,
    provider_model_id,
)
from .paths import (
    APP_USER_KEY,
    MARKER_KEY,
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
    return has_table(conn, "ItemTable")


def has_table(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
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


def unique_provider_ids(model_ids: list[str]) -> list[str]:
    return list(dict.fromkeys(provider_model_id(model_id) for model_id in model_ids))


def sequence(value: object) -> list[Any]:
    return list(value) if isinstance(value, (list, tuple, set)) else []


def merge_enabled_models(current: object, provider_ids: list[str]) -> list[str]:
    values = []
    for item in sequence(current):
        if isinstance(item, str):
            values.append(provider_model_id(item))
    for model_id in provider_ids:
        values.append(model_id)
    return list(dict.fromkeys(values))


def remove_model_overrides(current: object, provider_ids: list[str]) -> list[str]:
    provider_set = set(provider_ids)
    aliases = {cursor_model_id(model_id) for model_id in provider_ids}
    values = []
    for item in sequence(current):
        if item in provider_set or item in aliases:
            continue
        values.append(item)
    return values


def register_models(data: dict[str, Any], model_ids: list[str]) -> None:
    provider_ids = unique_provider_ids(model_ids)
    data["availableAPIKeyModels"] = provider_ids
    data["localProviderModelIds"] = provider_ids

    ai_settings = data.setdefault("aiSettings", {})
    for key in ("userAddedModels", "modelOverrideEnabled"):
        ai_settings[key] = merge_enabled_models(ai_settings.get(key), provider_ids)
    for key in ("modelOverrideDisabled", "modelsWithNoDefaultSwitch"):
        if key in ai_settings:
            ai_settings[key] = remove_model_overrides(ai_settings.get(key), provider_ids)

    catalog = list(data.get("availableDefaultModels2") or [])
    by_name = {}
    for item in catalog:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not isinstance(name, str) or is_cursor_vibemode_model(name):
            continue
        by_name[name] = item
    for model_id in provider_ids:
        if model_id not in by_name or by_name[model_id].get("isUserAdded") is True:
            by_name[model_id] = model_catalog_entry(model_id, by_name.get(model_id))
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
    provider_id = provider_model_id(model_id)
    normalize_alias_values(data)
    data["openAIBaseUrl"] = base_url.rstrip("/")
    data["useOpenAIKey"] = True
    register_models(data, model_ids)
    set_default_model(data, provider_id)
    return data


def normalize_alias_values(value: Any) -> bool:
    changed = False
    if isinstance(value, dict):
        for key, item in list(value.items()):
            target_key = provider_model_id(key) if is_cursor_vibemode_model(key) else key
            if target_key != key:
                value.pop(key)
                item = merge_alias_key_value(value.get(target_key), item)
                value[target_key] = item
                changed = True
            if is_cursor_vibemode_model(item):
                value[target_key] = provider_model_id(item)
                changed = True
            elif isinstance(item, (dict, list)):
                changed = normalize_alias_values(item) or changed
    elif isinstance(value, list):
        for index, item in enumerate(value):
            if is_cursor_vibemode_model(item):
                value[index] = provider_model_id(item)
                changed = True
            elif isinstance(item, (dict, list)):
                changed = normalize_alias_values(item) or changed
    return changed


def merge_alias_key_value(current: Any, incoming: Any) -> Any:
    if current is None:
        return incoming
    if isinstance(current, (int, float)) and isinstance(incoming, (int, float)):
        return max(current, incoming)
    return current


def cleanup_cursor_disk_models(conn: sqlite3.Connection) -> None:
    if not has_table(conn, "cursorDiskKV"):
        return
    rows = conn.execute(
        "SELECT key, value FROM cursorDiskKV WHERE key LIKE 'composerData:%'"
    ).fetchall()
    for key, raw_value in rows:
        text = (
            raw_value.decode("utf-8", errors="replace")
            if isinstance(raw_value, bytes)
            else str(raw_value)
        )
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if not isinstance(data, dict) or not normalize_alias_values(data):
            continue
        conn.execute(
            "UPDATE cursorDiskKV SET value=? WHERE key=?",
            (json.dumps(data, ensure_ascii=False, separators=(",", ":")), key),
        )


def read_registered_models(data: dict[str, Any]) -> list[str]:
    models: list[str] = []
    for key in ("localProviderModelIds", "availableAPIKeyModels"):
        for item in sequence(data.get(key)):
            if isinstance(item, str):
                models.append(provider_model_id(item))
    for item in sequence(data.get("availableDefaultModels2")):
        if not isinstance(item, dict):
            continue
        model_id = catalog_provider_model_id(item)
        if model_id:
            models.append(provider_model_id(model_id))
    return list(dict.fromkeys(models))


def read_status(db_path: Path) -> CursorStatus:
    if not db_path.is_file():
        return CursorStatus(db_path, False, False, None, "", "", [])
    with closing(connect(db_path)) as conn:
        if not has_item_table(conn):
            return CursorStatus(db_path, False, False, None, "", "", [])
        app_user = read_json_value(conn, APP_USER_KEY)
        composer_model = str(app_user.get("composerModel") or "")
        return CursorStatus(
            db_path=db_path,
            has_item_table=True,
            has_key=bool(get_value(conn, OPENAI_KEY_STORAGE)),
            use_openai_key=app_user.get("useOpenAIKey"),
            base_url=str(app_user.get("openAIBaseUrl") or ""),
            composer_model=provider_model_id(composer_model),
            registered_models=read_registered_models(app_user),
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
        selected_model = provider_model_id(model_id)
        models = list(
            dict.fromkeys(
                provider_model_id(model) for model in (model_ids or list(VIBEMODE_MODELS))
            )
        )
        if selected_model not in models:
            models.insert(0, selected_model)
        app_user = patch_application_user(
            app_user,
            base_url=base_url,
            model_id=selected_model,
            model_ids=models,
        )
        write_json_value(conn, APP_USER_KEY, app_user)
        set_value(conn, OPENAI_KEY_STORAGE, api_key)
        cleanup_cursor_disk_models(conn)
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
