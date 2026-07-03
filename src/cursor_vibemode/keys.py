from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from io import TextIOWrapper
from pathlib import Path

from .paths import local_auth_path


ENV_KEYS = ("CURSOR_VIBEMODE_KEY", "VIBEMODE_API_KEY")


@dataclass(frozen=True)
class KeyResult:
    value: str
    source: str


def trim_key(value: str | None) -> str:
    return (value or "").strip()


def read_json_key(path: Path, keys: tuple[str, ...]) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def saved_local_key() -> str:
    return read_json_key(local_auth_path(), ("api_key", "CURSOR_VIBEMODE_KEY"))


def save_local_key(key: str) -> None:
    path = local_auth_path()
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    tmp.write_text(json.dumps({"api_key": key}, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)
    os.chmod(path, 0o600)


def remove_local_key() -> bool:
    path = local_auth_path()
    if not path.exists():
        return False
    path.unlink()
    return True


def read_secret(label: str) -> str:
    stream = sys.stderr
    stream.write(label)
    stream.flush()
    input_stream = open_tty_stdin()
    close_input = input_stream is not sys.stdin
    if not input_stream.isatty():
        try:
            value = input_stream.readline().strip()
        finally:
            if close_input:
                input_stream.close()
        stream.write("\n")
        stream.flush()
        return value

    import termios
    import tty

    fd = input_stream.fileno()
    old = termios.tcgetattr(fd)
    value = []
    try:
        tty.setraw(fd)
        while True:
            char = input_stream.read(1)
            if char in {"\r", "\n"}:
                break
            if char == "\x03":
                raise KeyboardInterrupt
            if char in {"\x7f", "\b"}:
                if value:
                    value.pop()
                    stream.write("\b \b")
                    stream.flush()
                continue
            value.append(char)
            stream.write("*")
            stream.flush()
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
        if close_input:
            input_stream.close()
        stream.write("\n")
        stream.flush()
    return "".join(value).strip()


def open_tty_stdin() -> TextIOWrapper:
    try:
        return open("/dev/tty", "r", encoding="utf-8")
    except OSError:
        return sys.stdin


def prompt_new_key() -> KeyResult:
    key = read_secret("Paste Vibemode API key: ")
    if not key:
        raise RuntimeError("API key not provided")
    return KeyResult(key, "prompt")


def choose_existing_key(label: str, key: str) -> KeyResult:
    answer = read_secret(f"{label}. Enter = use, r = replace, or paste new key: ")
    if not answer:
        return KeyResult(key, label)
    if answer.lower() in {"r", "replace", "new", "n"}:
        return prompt_new_key()
    return KeyResult(answer, "prompt")


def resolve_api_key(
    *,
    explicit_key: str | None,
    replace_key: bool,
    non_interactive: bool,
    cursor_key: str = "",
) -> KeyResult:
    if trim_key(explicit_key):
        return KeyResult(trim_key(explicit_key), "--key")
    for name in ENV_KEYS:
        if trim_key(os.environ.get(name)):
            return KeyResult(trim_key(os.environ[name]), name)

    if not replace_key:
        local = saved_local_key()
        if local and non_interactive:
            return KeyResult(local, str(local_auth_path()))
        if local:
            return choose_existing_key("Saved cursor-vibemode key found", local)
        if cursor_key and non_interactive:
            return KeyResult(cursor_key, "Cursor state.vscdb")
        if cursor_key:
            return choose_existing_key("Cursor OpenAI key found", cursor_key)

    if non_interactive:
        raise RuntimeError("API key not found. Set CURSOR_VIBEMODE_KEY or pass --key.")
    return prompt_new_key()
