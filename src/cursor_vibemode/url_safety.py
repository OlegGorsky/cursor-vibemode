from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from .paths import DEFAULT_ADAPTER_PORT


PRIVATE_HOST_MESSAGE = (
    "адрес API выглядит локальным или приватным; обычный Cursor может его отклонить."
)


def host_warnings(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return ["Base URL has no host."]
    warnings: list[str] = []
    if parsed.scheme != "https":
        warnings.append("адрес API не HTTPS; Cursor может отклонить такое подключение.")
    if is_private_host(host):
        warnings.append(PRIVATE_HOST_MESSAGE)
    return warnings


def status_host_warnings(base_url: str) -> list[str]:
    if is_internal_adapter_url(base_url):
        return []
    return host_warnings(base_url)


def is_internal_adapter_url(base_url: str) -> bool:
    parsed = urlparse(base_url)
    try:
        port = parsed.port or 0
    except ValueError:
        return False
    return parsed.hostname in {"127.0.0.1", "localhost"} and (
        DEFAULT_ADAPTER_PORT <= port < DEFAULT_ADAPTER_PORT + 20
    )


def is_private_host(host: str) -> bool:
    clean = host.strip("[]").lower()
    if clean in {"localhost", "0.0.0.0"} or clean.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(clean)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
