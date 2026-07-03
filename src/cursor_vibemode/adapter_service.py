from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import CursorVibemodeError
from .adapter_process import (
    adapter_base_url,
    adapter_is_current,
    adapter_log_tail,
    is_our_adapter,
    port_available,
    start_adapter,
    wait_until_ready,
)
from .paths import (
    DEFAULT_ADAPTER_PORT,
    adapter_config_path,
    adapter_runtime_dir,
)


@dataclass(frozen=True)
class AdapterReport:
    base_url: str
    port: int


def ensure_adapter(upstream_base_url: str, api_key: str = "") -> AdapterReport:
    port = choose_port()
    write_config(upstream_base_url, port, api_key)
    install_runtime()
    write_launchers()
    install_autostart()
    start_adapter(port)
    base_url = adapter_base_url(port)
    if not wait_until_ready(base_url):
        raise CursorVibemodeError(
            "ADAPTER_START_FAILED",
            "не удалось запустить подключение моделей",
            "Локальный слой совместимости не ответил на проверку.",
            "повтори установку; если ошибка останется, передай вывод разработчику.",
            adapter_start_detail(base_url),
        )
    return AdapterReport(base_url, port)


def adapter_start_detail(base_url: str) -> str:
    detail = f"baseUrl={base_url}; runtime={adapter_runtime_dir()}"
    tail = adapter_log_tail()
    if tail:
        detail += f"; logTail={tail}"
    return detail


def choose_port() -> int:
    current = read_config_port()
    if current and adapter_is_current(current):
        return current
    for port in range(DEFAULT_ADAPTER_PORT, DEFAULT_ADAPTER_PORT + 20):
        if current == port and is_our_adapter(port):
            continue
        if adapter_is_current(port) or port_available(port):
            return port
    raise CursorVibemodeError(
        "ADAPTER_PORT_UNAVAILABLE",
        "не удалось выбрать локальный порт",
        "Все стандартные порты подключения моделей заняты.",
        "освободи порт 17654 или передай вывод разработчику.",
    )


def read_config_port() -> int | None:
    try:
        data = json.loads(adapter_config_path().read_text(encoding="utf-8"))
        return int(data.get("port") or 0) or None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def write_config(upstream_base_url: str, port: int, api_key: str = "") -> None:
    path = adapter_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "upstream_base_url": upstream_base_url.rstrip("/"),
        "host": "127.0.0.1",
        "port": port,
        "cache_ttl_seconds": 300,
        "api_key": api_key,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def install_runtime() -> None:
    runtime = adapter_runtime_dir()
    src_root = Path(__file__).resolve().parents[1]
    dest_src = runtime / "src"
    runtime.mkdir(parents=True, exist_ok=True)
    if dest_src.exists():
        shutil.rmtree(dest_src)
    shutil.copytree(src_root, dest_src, ignore=shutil.ignore_patterns("__pycache__"))


def write_launchers() -> None:
    runtime = adapter_runtime_dir()
    runtime.mkdir(parents=True, exist_ok=True)
    src = runtime / "src"
    if os.name == "nt":
        launcher = runtime / "run-adapter.cmd"
        launcher.write_text(
            "@echo off\r\n"
            f"set \"PYTHONPATH={src}\"\r\n"
            f"\"{sys.executable}\" -m cursor_vibemode adapter serve\r\n",
            encoding="utf-8",
        )
    else:
        launcher = runtime / "run-adapter.sh"
        launcher.write_text(
            "#!/usr/bin/env sh\n"
            f"export PYTHONPATH={shell_quote(str(src))}\n"
            f"exec {shell_quote(sys.executable)} -m cursor_vibemode adapter serve\n",
            encoding="utf-8",
        )
        launcher.chmod(0o755)


def install_autostart() -> None:
    if sys.platform == "win32":
        install_windows_autostart()
    elif sys.platform == "darwin":
        install_macos_autostart()
    else:
        install_linux_autostart()


def install_linux_autostart() -> None:
    runtime = adapter_runtime_dir()
    unit_dir = Path.home() / ".config" / "systemd" / "user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    unit = unit_dir / "cursor-vibemode-adapter.service"
    unit.write_text(
        "[Unit]\n"
        "Description=Cursor Vibemode model connection\n\n"
        "[Service]\n"
        "Type=simple\n"
        f"ExecStart={runtime / 'run-adapter.sh'}\n"
        "Restart=always\n"
        "RestartSec=2\n\n"
        "[Install]\n"
        "WantedBy=default.target\n",
        encoding="utf-8",
    )
    try:
        reload_result = run_quiet(["systemctl", "--user", "daemon-reload"], 5)
        enable_result = run_quiet(["systemctl", "--user", "enable", unit.name], 10)
        restart_result = run_quiet(["systemctl", "--user", "restart", unit.name], 10)
        if (
            reload_result.returncode != 0
            or enable_result.returncode != 0
            or restart_result.returncode != 0
        ):
            write_desktop_autostart()
    except (OSError, subprocess.SubprocessError):
        write_desktop_autostart()


def write_desktop_autostart() -> None:
    app_dir = Path.home() / ".config" / "autostart"
    app_dir.mkdir(parents=True, exist_ok=True)
    desktop = app_dir / "cursor-vibemode-adapter.desktop"
    desktop.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Cursor Vibemode\n"
        f"Exec={adapter_runtime_dir() / 'run-adapter.sh'}\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )


def install_macos_autostart() -> None:
    plist_dir = Path.home() / "Library" / "LaunchAgents"
    plist_dir.mkdir(parents=True, exist_ok=True)
    plist = plist_dir / "com.cursor-vibemode.adapter.plist"
    launcher = adapter_runtime_dir() / "run-adapter.sh"
    plist.write_text(
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<!DOCTYPE plist PUBLIC \"-//Apple//DTD PLIST 1.0//EN\" "
        "\"http://www.apple.com/DTDs/PropertyList-1.0.dtd\">\n"
        "<plist version=\"1.0\"><dict>\n"
        "<key>Label</key><string>com.cursor-vibemode.adapter</string>\n"
        "<key>ProgramArguments</key><array>"
        f"<string>{launcher}</string>"
        "</array>\n"
        "<key>RunAtLoad</key><true/>\n"
        "<key>KeepAlive</key><true/>\n"
        "</dict></plist>\n",
        encoding="utf-8",
    )
    for action in ("unload", "load"):
        run_quiet(["launchctl", action, str(plist)], 10)


def install_windows_autostart() -> None:
    launcher = adapter_runtime_dir() / "run-adapter.cmd"
    run_quiet(
        [
            "schtasks",
            "/Create",
            "/SC",
            "ONLOGON",
            "/TN",
            "CursorVibemodeAdapter",
            "/TR",
            f'"{launcher}"',
            "/F",
        ],
        10,
    )


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def run_quiet(command: list[str], timeout: int) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            command,
            check=False,
            timeout=timeout,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return subprocess.CompletedProcess(command, 1)
