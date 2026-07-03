from __future__ import annotations

import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import CursorVibemodeError


APP_COPY_RELS = {
    Path("product.json"),
    Path("out/main.js"),
    Path("out/vs/workbench/workbench.desktop.main.js"),
    Path("out/vs/workbench/workbench.glass.main.js"),
}
APP_COPY_DIRS = {"extensions"}


@dataclass(frozen=True)
class ShadowCursorApp:
    app_root: Path
    launcher: Path
    desktop_entry: Path | None


def create_shadow_cursor_app(source_app_root: Path) -> ShadowCursorApp | None:
    if sys.platform != "linux":
        return None
    source_root = source_app_root.parent.parent
    source_exe = source_root / "cursor"
    if not source_exe.is_file():
        return None

    dest_root = shadow_install_root(source_app_root)
    base = shadow_base_dir()
    try:
        reset_shadow_dir(dest_root, base)
        mirror_install_root(source_root, source_app_root, dest_root)
        launcher = write_launcher(dest_root)
        desktop = write_desktop_entry(launcher)
        point_current_to(dest_root, base)
    except OSError as error:
        raise CursorVibemodeError(
            "CURSOR_APP_SHADOW_FAILED",
            "не удалось создать пользовательский запуск Cursor",
            "Системная установка Cursor недоступна для записи, а локальную копию создать не удалось.",
            "проверь права на ~/.local/share и повтори запуск.",
            repr(error),
        ) from error
    return ShadowCursorApp(dest_root / "resources" / "app", launcher, desktop)


def existing_shadow_cursor_app(source_app_root: Path) -> ShadowCursorApp | None:
    dest_root = shadow_install_root(source_app_root)
    app_root = dest_root / "resources" / "app"
    if app_root.is_dir():
        repair_shadow_entrypoints(source_app_root.parent.parent, dest_root)
        repair_shadow_extensions(source_app_root, app_root)
        launcher = write_launcher(dest_root)
        desktop = write_desktop_entry(launcher)
        return ShadowCursorApp(app_root, launcher, desktop)
    return None


def shadow_launcher_for_app(app_root: Path) -> Path | None:
    if not is_inside(app_root, shadow_base_dir()):
        return None
    dest_root = app_root.parent.parent
    launcher = write_launcher(dest_root)
    write_desktop_entry(launcher)
    return launcher


def desktop_entry_path() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "applications" / "cursor-vibemode.desktop"


def mirror_install_root(source_root: Path, source_app_root: Path, dest_root: Path) -> None:
    dest_root.mkdir(parents=True)
    for item in source_root.iterdir():
        dest = dest_root / item.name
        if item.name == "cursor" and item.is_file():
            copy_writable(item, dest, executable=True)
        elif item.name == "bin" and item.is_dir():
            mirror_bin_dir(item, dest)
        elif item.name == "resources" and item.is_dir():
            mirror_resources(item, source_app_root, dest)
        else:
            dest.symlink_to(item, target_is_directory=item.is_dir())


def repair_shadow_entrypoints(source_root: Path, dest_root: Path) -> None:
    source_exe = source_root / "cursor"
    if source_exe.is_file():
        copy_writable(source_exe, dest_root / "cursor", executable=True)
    source_bin = source_root / "bin"
    dest_bin = dest_root / "bin"
    if source_bin.is_dir():
        if dest_bin.is_symlink() or dest_bin.is_file():
            dest_bin.unlink()
        if not dest_bin.exists():
            mirror_bin_dir(source_bin, dest_bin)
        elif dest_bin.is_dir() and (source_bin / "cursor").is_file():
            copy_writable(source_bin / "cursor", dest_bin / "cursor", executable=True)


def mirror_bin_dir(source_bin: Path, dest_bin: Path) -> None:
    dest_bin.mkdir()
    for item in source_bin.iterdir():
        dest = dest_bin / item.name
        if item.name == "cursor" and item.is_file():
            copy_writable(item, dest, executable=True)
        else:
            dest.symlink_to(item, target_is_directory=item.is_dir())


def mirror_resources(source_resources: Path, source_app_root: Path, dest_resources: Path) -> None:
    dest_resources.mkdir()
    for item in source_resources.iterdir():
        dest = dest_resources / item.name
        if item == source_app_root:
            mirror_app_tree(item, dest)
        else:
            dest.symlink_to(item, target_is_directory=item.is_dir())


def mirror_app_tree(source_app: Path, dest_app: Path) -> None:
    dest_app.mkdir()
    for source in source_app.rglob("*"):
        rel = source.relative_to(source_app)
        dest = dest_app / rel
        if source.is_symlink():
            if should_copy_app_file(rel) and source.is_file():
                copy_writable(source.resolve(), dest, executable=is_executable(source))
            else:
                dest.symlink_to(source)
        elif source.is_dir():
            dest.mkdir(exist_ok=True)
        elif should_copy_app_file(rel):
            copy_writable(source, dest, executable=is_executable(source))
        else:
            dest.symlink_to(source)


def repair_shadow_extensions(source_app: Path, dest_app: Path) -> None:
    source_extensions = source_app / "extensions"
    dest_extensions = dest_app / "extensions"
    if not source_extensions.is_dir():
        return
    if dest_extensions.exists() and not extension_tree_needs_repair(dest_extensions):
        return
    if dest_extensions.exists() or dest_extensions.is_symlink():
        dest_extensions.unlink() if dest_extensions.is_symlink() else shutil.rmtree(dest_extensions)
    copy_tree_writable(source_extensions, dest_extensions)


def extension_tree_needs_repair(dest_extensions: Path) -> bool:
    required = (
        "cursor-agent-exec/dist/main.js",
        "cursor-always-local/dist/main.js",
        "cursor-mcp/dist/main.js",
    )
    for rel in required:
        path = dest_extensions / rel
        if not path.is_file() or path.is_symlink():
            return True
    return False


def should_copy_app_file(rel: Path) -> bool:
    return rel in APP_COPY_RELS or (rel.parts and rel.parts[0] in APP_COPY_DIRS)


def copy_tree_writable(source: Path, dest: Path) -> None:
    shutil.copytree(source, dest, symlinks=False)


def copy_writable(source: Path, dest: Path, *, executable: bool = False) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() or dest.is_symlink():
        dest.unlink()
    shutil.copy2(source, dest)
    dest.chmod(0o755 if executable else 0o644)


def is_executable(path: Path) -> bool:
    return bool(path.stat().st_mode & 0o111)


def write_launcher(dest_root: Path) -> Path:
    launcher_dir = Path.home() / ".local" / "bin"
    launcher_dir.mkdir(parents=True, exist_ok=True)
    launcher = launcher_dir / "cursor-vibemode"
    executable = cursor_entrypoint(dest_root)
    launcher.write_text(
        "#!/usr/bin/env sh\n"
        f"exec {shell_quote(str(executable))} \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    return launcher


def cursor_entrypoint(dest_root: Path) -> Path:
    cli = dest_root / "bin" / "cursor"
    return cli if cli.is_file() else dest_root / "cursor"


def write_desktop_entry(launcher: Path) -> Path | None:
    desktop = desktop_entry_path()
    app_dir = desktop.parent
    app_dir.mkdir(parents=True, exist_ok=True)
    desktop.write_text(
        "[Desktop Entry]\n"
        "Name=Cursor Vibemode\n"
        "Comment=Cursor with Vibemode local mode\n"
        f"Exec={launcher} %U\n"
        "Icon=cursor\n"
        "Type=Application\n"
        "Categories=Development;IDE;\n"
        "StartupNotify=true\n",
        encoding="utf-8",
    )
    return desktop


def point_current_to(dest_root: Path, base: Path) -> None:
    current = base / "current"
    tmp = base / "current.tmp"
    if tmp.exists() or tmp.is_symlink():
        tmp.unlink()
    tmp.symlink_to(dest_root, target_is_directory=True)
    if current.exists() or current.is_symlink():
        current.unlink() if current.is_symlink() else shutil.rmtree(current)
    tmp.rename(current)


def reset_shadow_dir(dest_root: Path, base: Path) -> None:
    base.mkdir(parents=True, exist_ok=True)
    if not is_inside(dest_root, base):
        raise OSError(f"refusing to remove path outside shadow base: {dest_root}")
    if dest_root.exists() or dest_root.is_symlink():
        dest_root.unlink() if dest_root.is_symlink() else shutil.rmtree(dest_root)


def shadow_install_root(source_app_root: Path) -> Path:
    return shadow_base_dir() / fingerprint(source_app_root)


def shadow_base_dir() -> Path:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return data_home / "cursor-vibemode" / "cursor"


def fingerprint(path: Path) -> str:
    resolved = str(path.resolve())
    return hashlib.sha1(resolved.encode("utf-8")).hexdigest()[:16]


def is_inside(path: Path, base: Path) -> bool:
    resolved_path = path.resolve(strict=False)
    resolved_base = base.resolve(strict=False)
    return resolved_path == resolved_base or resolved_base in resolved_path.parents


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"
