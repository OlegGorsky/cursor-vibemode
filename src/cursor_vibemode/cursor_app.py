from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

from .cursor_app_shadow import (
    create_shadow_cursor_app,
    existing_shadow_cursor_app,
    shadow_launcher_for_app,
)
from .cursor_app_paths import detect_cursor_app_root
from .errors import CursorVibemodeError


LOCAL_MODE_DISABLED = "cursorPredictionOptions:!1,localMode:!1"
LOCAL_MODE_ENABLED = "cursorPredictionOptions:!1,localMode:!0"

PATCH_TARGETS = (
    ("out/vs/workbench/workbench.desktop.main.js", "vs/workbench/workbench.desktop.main.js"),
    ("out/vs/workbench/workbench.glass.main.js", "vs/workbench/workbench.glass.main.js"),
    ("out/main.js", "main.js"),
)


@dataclass(frozen=True)
class CursorAppInspection:
    app_root: Path | None
    state: str
    writable: bool

    @property
    def display(self) -> str:
        if self.state == "enabled":
            return "включен"
        if self.state == "disabled":
            return "нужно включить"
        if self.state == "not_required":
            return "не требуется для этой версии"
        if self.state == "unknown":
            return "не определен"
        return "приложение Cursor не найдено"


@dataclass(frozen=True)
class CursorAppPatchReport:
    app_root: Path
    changed_files: tuple[str, ...]
    already_enabled: bool
    not_required: bool = False
    launcher: Path | None = None

    @property
    def display(self) -> str:
        if self.not_required:
            return "не требуется для этой версии"
        if self.already_enabled:
            return "уже включен"
        return "включен"


def inspect_cursor_app(explicit_root: str | None = None) -> CursorAppInspection:
    root = detect_cursor_app_root(explicit_root)
    if not root:
        return CursorAppInspection(None, "not_found", False)

    disabled = 0
    enabled = 0
    local_refs = 0
    writable = True
    for target, _ in existing_targets(root):
        text = read_text(target)
        disabled += text.count(LOCAL_MODE_DISABLED)
        enabled += text.count(LOCAL_MODE_ENABLED)
        local_refs += text.count("localMode")
        if LOCAL_MODE_DISABLED in text and not is_writable(target):
            writable = False

    if disabled:
        product = root / "product.json"
        if checksum_update_needed(root) and not is_writable(product):
            writable = False
        return CursorAppInspection(root, "disabled", writable)
    if enabled:
        return CursorAppInspection(root, "enabled", True)
    if local_refs == 0:
        return CursorAppInspection(root, "not_required", True)
    return CursorAppInspection(root, "unknown", writable)


def patch_cursor_app(explicit_root: str | None = None) -> CursorAppPatchReport:
    root = detect_cursor_app_root(explicit_root, include_shadow=bool(explicit_root))
    if not root and not explicit_root:
        root = detect_cursor_app_root()
    if not root:
        raise CursorVibemodeError(
            "CURSOR_APP_NOT_FOUND",
            "приложение Cursor не найдено",
            "Скрипт нашел профиль Cursor, но не нашел установленное приложение для патча.",
            "укажи путь через --app-root или установи Cursor стандартным способом.",
        )

    inspection = inspect_cursor_app(str(root))
    if inspection.state == "enabled":
        return CursorAppPatchReport(root, (), True, launcher=shadow_launcher_for_app(root))
    if inspection.state == "not_required":
        return CursorAppPatchReport(root, (), True, not_required=True)
    if inspection.state == "unknown":
        raise CursorVibemodeError(
            "CURSOR_APP_PATTERN_NOT_FOUND",
            "не удалось распознать внутренний режим Cursor",
            "В этой версии Cursor изменился JS-бандл, и известный патч localMode не найден.",
            "передай вывод doctor разработчику.",
            f"appRoot={root}",
        )
    if not inspection.writable:
        existing_shadow = existing_shadow_cursor_app(root)
        if existing_shadow and inspect_cursor_app(str(existing_shadow.app_root)).state == "enabled":
            return CursorAppPatchReport(
                existing_shadow.app_root,
                (),
                True,
                launcher=existing_shadow.launcher,
            )
        shadow = create_shadow_cursor_app(root)
        if shadow:
            changed = patch_targets(shadow.app_root)
            update_product_checksums(shadow.app_root, changed)
            return CursorAppPatchReport(
                shadow.app_root,
                tuple(path for path, _ in changed),
                False,
                launcher=shadow.launcher,
            )
        raise readonly_app_error(root)

    changed = patch_targets(root)
    update_product_checksums(root, changed)
    return CursorAppPatchReport(root, tuple(path for path, _ in changed), False)


def readonly_app_error(root: Path) -> CursorVibemodeError:
    return CursorVibemodeError(
        "CURSOR_APP_PATCH_READONLY",
        "установка Cursor недоступна для записи",
        "Профиль Cursor можно настроить, но само приложение нельзя пропатчить в этом месте.",
        "используй writable-установку Cursor или передай разработчику путь из блока ниже.",
        f"appRoot={root}",
    )


def patch_targets(root: Path) -> list[tuple[str, str]]:
    changed: list[tuple[str, str]] = []
    for target, checksum_key in existing_targets(root):
        text = read_text(target)
        if LOCAL_MODE_DISABLED not in text:
            continue
        backup_file(target)
        target.write_text(text.replace(LOCAL_MODE_DISABLED, LOCAL_MODE_ENABLED), encoding="utf-8")
        changed.append((target.relative_to(root).as_posix(), checksum_key))
    return changed


def update_product_checksums(root: Path, changed: list[tuple[str, str]]) -> None:
    product = root / "product.json"
    if not changed or not product.is_file():
        return
    data = json.loads(product.read_text(encoding="utf-8"))
    checksums = data.get("checksums")
    if not isinstance(checksums, dict):
        return
    touched = False
    for rel_path, checksum_key in changed:
        key = checksum_key if checksum_key in checksums else rel_path.removeprefix("out/")
        if key not in checksums:
            continue
        checksums[key] = checksum(root / rel_path)
        touched = True
    if touched:
        backup_file(product)
        product.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def checksum_update_needed(root: Path) -> bool:
    product = root / "product.json"
    if not product.is_file():
        return False
    try:
        data = json.loads(product.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    checksums = data.get("checksums")
    if not isinstance(checksums, dict):
        return False
    return any(key in checksums or rel.removeprefix("out/") in checksums for rel, key in PATCH_TARGETS)


def existing_targets(root: Path) -> list[tuple[Path, str]]:
    return [(root / rel, checksum_key) for rel, checksum_key in PATCH_TARGETS if (root / rel).is_file()]


def is_writable(path: Path) -> bool:
    return path.exists() and os.access(path, os.W_OK)


def checksum(path: Path) -> str:
    digest = hashlib.sha256(path.read_bytes()).digest()
    return base64.b64encode(digest).decode("ascii").rstrip("=")


def backup_file(path: Path) -> None:
    backup = path.with_name(f"{path.name}.cursor-vibemode.bak")
    if not backup.exists():
        backup.write_bytes(path.read_bytes())


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")
