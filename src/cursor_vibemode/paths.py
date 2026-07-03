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
    seen: set[Path] = set()
    result: list[Path] = []
    for path in paths:
        path = path.expanduser()
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def find_cursor_db(explicit: str | None = None) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        return path if path.is_file() else None
    for path in candidate_db_paths():
        if path.is_file():
            return path
    return None


def cursor_processes() -> list[str]:
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


def mask_secret(value: str | None) -> str:
    if not value:
        return "missing"
    clean = value.strip()
    if len(clean) <= 12:
        return "[saved]"
    return f"{clean[:6]}...{clean[-4:]}"
