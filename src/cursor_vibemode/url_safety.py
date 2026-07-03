from __future__ import annotations

import ipaddress
from urllib.parse import urlparse


PRIVATE_HOST_MESSAGE = (
    "Cursor can block private or localhost Override OpenAI Base URL values. "
    "Use a public HTTPS tunnel if Cursor cannot reach this endpoint."
)


def host_warnings(base_url: str) -> list[str]:
    parsed = urlparse(base_url)
    host = parsed.hostname or ""
    if not host:
        return ["Base URL has no host."]
    warnings: list[str] = []
    if parsed.scheme != "https":
        warnings.append("Base URL is not HTTPS; Cursor may reject or block it.")
    if is_private_host(host):
        warnings.append(PRIVATE_HOST_MESSAGE)
    return warnings


def is_private_host(host: str) -> bool:
    clean = host.strip("[]").lower()
    if clean in {"localhost", "0.0.0.0"} or clean.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(clean)
    except ValueError:
        return False
    return address.is_private or address.is_loopback or address.is_link_local
