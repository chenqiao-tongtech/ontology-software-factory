"""Shared network exposure checks for unauthenticated local reference consoles."""
from __future__ import annotations

from urllib.parse import urlsplit


LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def is_loopback_bind(host: str) -> bool:
    """Accept only explicit loopback bind names; aliases and wildcard binds fail closed."""
    return str(host).strip().lower() in LOOPBACK_HOSTS


def same_origin_request(origin: str | None, host_header: str) -> bool:
    """Allow non-browser clients without Origin; reject malformed or cross-origin browser writes."""
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc.lower() == host_header.lower()
    except ValueError:
        return False
