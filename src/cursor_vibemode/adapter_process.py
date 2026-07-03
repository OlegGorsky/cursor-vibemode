from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

from .paths import ADAPTER_VERSION, adapter_runtime_dir


def is_windows() -> bool:
    return sys.platform == "win32"


def adapter_base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}/v1"


def start_adapter(port: int) -> None:
    if adapter_is_current(port):
        return
    runtime = adapter_runtime_dir()
    log = runtime / "adapter.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    command, env = adapter_command_env()
    with log.open("ab") as stream:
        try:
            subprocess.Popen(
                command,
                stdout=stream,
                stderr=stream,
                stdin=subprocess.DEVNULL,
                env=env,
                **popen_flags(),
            )
        except OSError as error:
            stream.write(f"\n[start failed] {error!r}\n".encode("utf-8", errors="replace"))


def adapter_command_env() -> tuple[list[str], dict[str, str] | None]:
    runtime = adapter_runtime_dir()
    if is_windows():
        env = os.environ.copy()
        env["PYTHONPATH"] = str(runtime / "src")
        return [sys.executable, "-m", "cursor_vibemode", "adapter", "serve"], env
    launcher = runtime / "run-adapter.sh"
    return [str(launcher)], None


def popen_flags() -> dict:
    if is_windows():
        creationflags = 0
        for name in ("CREATE_NEW_PROCESS_GROUP", "CREATE_NO_WINDOW", "DETACHED_PROCESS"):
            creationflags |= int(getattr(subprocess, name, 0))
        return {"close_fds": False, "creationflags": creationflags}
    return {"close_fds": True, "start_new_session": True}


def wait_until_ready(base_url: str, timeout: float | None = None) -> bool:
    timeout = timeout if timeout is not None else (20.0 if is_windows() else 8.0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if adapter_is_current(int(base_url.rsplit(":", 1)[1].split("/", 1)[0])):
            return True
        time.sleep(0.2)
    return False


def is_our_adapter(port: int) -> bool:
    return bool(adapter_health(port))


def adapter_is_current(port: int) -> bool:
    payload = adapter_health(port)
    return bool(payload and int(payload.get("version") or 0) >= ADAPTER_VERSION)


def adapter_health(port: int) -> dict | None:
    try:
        with urllib.request.urlopen(
            f"{adapter_base_url(port)}/cursor-vibemode/health",
            timeout=1,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))
            if isinstance(payload, dict) and response.status == 200 and payload.get("ok") is True:
                return payload
            return None
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return None


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) != 0


def adapter_log_tail(limit: int = 2400) -> str:
    path = adapter_runtime_dir() / "adapter.log"
    try:
        data = path.read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace").strip()
