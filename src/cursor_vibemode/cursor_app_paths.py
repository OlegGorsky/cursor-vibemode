from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path


def detect_cursor_app_root(explicit_root: str | None = None, *, include_shadow: bool = True) -> Path | None:
    for candidate in candidate_app_roots(explicit_root, include_shadow=include_shadow):
        root = candidate.expanduser()
        if is_app_root(root):
            return root
    return None


def candidate_app_roots(explicit_root: str | None = None, *, include_shadow: bool = True) -> list[Path]:
    paths: list[Path] = []
    if explicit_root:
        paths.append(Path(explicit_root))
    env_root = os.environ.get("CURSOR_APP_ROOT")
    if env_root:
        paths.append(Path(env_root))
    if include_shadow:
        paths.extend(shadow_app_roots())
    paths.extend(process_app_roots())
    paths.extend(executable_app_roots())
    paths.extend(platform_app_roots())
    return unique_paths(paths)


def process_app_roots() -> list[Path]:
    if sys.platform == "win32":
        return windows_process_app_roots()
    try:
        result = subprocess.run(
            ["pgrep", "-af", "Cursor|cursor"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    roots: list[Path] = []
    for line in result.stdout.splitlines():
        for token in safe_split(line):
            roots.extend(app_roots_from_executable(Path(token)))
    return roots


def shadow_app_roots() -> list[Path]:
    data_home = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return [
        data_home / "cursor-vibemode" / "cursor" / "current" / "resources" / "app",
        Path.home() / ".cursor-vibemode" / "cursor" / "current" / "resources" / "app",
    ]


def windows_process_app_roots() -> list[Path]:
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-Process Cursor -ErrorAction SilentlyContinue).Path",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    roots: list[Path] = []
    for line in result.stdout.splitlines():
        if line.strip():
            roots.extend(app_roots_from_executable(Path(line.strip())))
    return roots


def app_roots_from_executable(path: Path) -> list[Path]:
    parent = path.parent
    return [
        parent / "resources" / "app",
        parent.parent / "resources" / "app",
        parent.parent / "lib" / "cursor" / "resources" / "app",
        parent.parent / "Resources" / "app",
        parent.parent / "Contents" / "Resources" / "app",
    ]


def executable_app_roots() -> list[Path]:
    roots: list[Path] = []
    for name in ("cursor", "Cursor", "cursor.exe", "Cursor.exe"):
        exe = shutil.which(name)
        if not exe:
            continue
        path = Path(exe)
        roots.extend(app_roots_from_executable(path))
        try:
            roots.extend(app_roots_from_executable(path.resolve()))
        except OSError:
            pass
    return roots


def platform_app_roots() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return [
            Path("/Applications/Cursor.app/Contents/Resources/app"),
            home / "Applications" / "Cursor.app" / "Contents" / "Resources" / "app",
        ]
    if sys.platform == "win32":
        return windows_app_roots()
    return [
        Path("/opt/Cursor/resources/app"),
        Path("/usr/share/cursor/resources/app"),
        Path("/usr/lib/cursor/resources/app"),
        Path("/usr/lib/Cursor/resources/app"),
        Path("/app/extra/cursor/resources/app"),
    ]


def windows_app_roots() -> list[Path]:
    roots: list[Path] = []
    for name in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(name)
        if base:
            roots.append(Path(base) / "Programs" / "Cursor" / "resources" / "app")
            roots.append(Path(base) / "Cursor" / "resources" / "app")
    return roots


def is_app_root(path: Path) -> bool:
    return (path / "product.json").is_file() and (path / "out").is_dir()


def safe_split(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def unique_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return result
