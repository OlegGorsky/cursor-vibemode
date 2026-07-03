from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


APP_USER_KEY = (
    "src.vs.platform.reactivestorage.browser.reactiveStorageServiceImpl"
    ".persistentStorage.applicationUser"
)
OPENAI_KEY_STORAGE = "cursorAuth/openAIKey"
MARKER_KEY = "__$__targetStorageMarker"

DEFAULT_BASE_URL = "https://api.vibemod.pro/v1"
DEFAULT_MODEL = "gpt-5.4"

AGENT_MODES = (
    "composer",
    "quick-agent",
    "cmd-k",
    "background-composer",
    "plan-execution",
)

VIBEMODE_MODELS = (
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.5",
    "deepseek-v4-pro",
    "deepseek-v4-flash",
    "glm-5.1",
    "kimi-k2.6",
    "minimax-m3",
    "qwen3.7-max",
    "qwen3.7-plus",
    "vibe-lite-1",
)

MODEL_LABELS = {
    "gpt-5.4": "GPT-5.4 [Vibemode]",
    "gpt-5.4-mini": "GPT-5.4 Mini [Vibemode]",
    "gpt-5.5": "GPT-5.5 [Vibemode]",
    "deepseek-v4-pro": "DeepSeek V4 Pro [Vibemode]",
    "deepseek-v4-flash": "DeepSeek V4 Flash [Vibemode]",
    "glm-5.1": "GLM 5.1 [Vibemode]",
    "kimi-k2.6": "Kimi K2.6 [Vibemode]",
    "minimax-m3": "MiniMax M3 [Vibemode]",
    "qwen3.7-max": "Qwen 3.7 Max [Vibemode]",
    "qwen3.7-plus": "Qwen 3.7 Plus [Vibemode]",
    "vibe-lite-1": "Vibe Lite 1 [Vibemode]",
}


def app_state_dir() -> Path:
    override = os.environ.get("CURSOR_VIBEMODE_HOME")
    return Path(override).expanduser() if override else Path.home() / ".cursor-vibemode"


def local_auth_path() -> Path:
    return app_state_dir() / "auth.json"


def cursor_config_roots() -> list[Path]:
    env = os.environ.get("CURSOR_CONFIG_HOME")
    if env:
        return [Path(env).expanduser()]
    if sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
        return [base / "Cursor"]
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        return [Path(appdata) / "Cursor"] if appdata else []
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return [base / "Cursor"]


def candidate_db_paths() -> list[Path]:
    paths: list[Path] = []
    if os.environ.get("CURSOR_DB"):
        paths.append(Path(os.environ["CURSOR_DB"]).expanduser())
    for root in cursor_config_roots():
        paths.append(root / "User" / "globalStorage" / "state.vscdb")
    paths.extend(wsl_windows_cursor_db_paths())
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        path = path.expanduser()
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def is_wsl() -> bool:
    if sys.platform != "linux":
        return False
    try:
        version = Path("/proc/version").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "microsoft" in version.lower() or "wsl" in version.lower()


def wsl_windows_cursor_db_paths() -> list[Path]:
    if not is_wsl():
        return []
    paths: list[Path] = []
    appdata = windows_appdata_from_wsl()
    if appdata:
        paths.append(appdata / "Cursor" / "User" / "globalStorage" / "state.vscdb")
    users = Path("/mnt/c/Users")
    if users.is_dir():
        paths.extend(users.glob("*/AppData/Roaming/Cursor/User/globalStorage/state.vscdb"))
    return paths


def windows_appdata_from_wsl() -> Path | None:
    try:
        result = subprocess.run(
            ["cmd.exe", "/c", "echo %APPDATA%"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    value = result.stdout.strip().replace("\r", "")
    if not value or "%" in value:
        return None
    converted = convert_windows_path_in_wsl(value)
    return converted if converted else None


def convert_windows_path_in_wsl(value: str) -> Path | None:
    try:
        result = subprocess.run(
            ["wslpath", "-u", value],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return Path(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass
    if len(value) >= 3 and value[1:3] == ":\\":
        drive = value[0].lower()
        rest = value[3:].replace("\\", "/")
        return Path(f"/mnt/{drive}/{rest}")
    return None


def find_cursor_db(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for path in candidate_db_paths():
        if path.is_file():
            return path
    return None


def cursor_processes() -> list[str]:
    if sys.platform == "win32":
        return windows_cursor_processes()

    names = ("Cursor", "cursor", "cursor-url-handler")
    found: list[str] = []
    for name in names:
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if result.returncode == 0:
            for pid in result.stdout.split():
                found.append(f"{name}:{pid}")
    return found


def windows_cursor_processes() -> list[str]:
    found: list[str] = []
    for name in ("Cursor.exe", "cursor.exe"):
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {name}", "/NH"],
                capture_output=True,
                text=True,
                check=False,
            )
        except OSError:
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            if line.lower().startswith(name.lower()):
                parts = line.split()
                pid = parts[1] if len(parts) > 1 else "?"
                found.append(f"{name}:{pid}")
    return found


def mask_secret(value: str | None) -> str:
    if not value:
        return "missing"
    clean = value.strip()
    if len(clean) <= 12:
        return "[saved]"
    return f"{clean[:6]}...{clean[-4:]}"
