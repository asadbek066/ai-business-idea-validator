"""Derive the address used to key per-client abuse limits.

By default only the socket peer is trusted. Forwarded headers are client
controlled unless a proxy the operator runs overwrites or appends to them, so
they are used only when explicitly configured:

* ``CLIENT_IP_HEADER`` names a single-value header the platform overwrites.
* ``TRUSTED_PROXY_COUNT`` (N > 0) takes the Nth-from-last ``X-Forwarded-For``
  entry, i.e. the address the outermost trusted proxy saw as its peer.

``CLIENT_IP_HEADER`` wins when both are set. Any missing or unparseable value
falls back to the socket peer.
"""

import ipaddress
import os
from typing import Any

from starlette.requests import Request


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return max(minimum, min(value, maximum))


TRUSTED_PROXY_COUNT = _bounded_env_int("TRUSTED_PROXY_COUNT", default=0, minimum=0, maximum=10)
CLIENT_IP_HEADER = os.getenv("CLIENT_IP_HEADER", "").strip().lower()


def normalize_ip(value: str) -> str | None:
    """Return a canonical key for an IP literal, or ``None`` if it is not one.

    IPv4-mapped IPv6 maps to IPv4; other IPv6 addresses are keyed on their /64.
    Scoped addresses (``fe80::1%eth0``) are rejected. This never raises.
    """

    try:
        text = value.strip()
        if "%" in text:  # zone ids parse on some Python versions only
            return None
        address = ipaddress.ip_address(text)
        if isinstance(address, ipaddress.IPv6Address):
            if address.ipv4_mapped is not None:
                return str(address.ipv4_mapped)
            prefix = ipaddress.IPv6Address(int(address) >> 64 << 64)
            return f"{prefix}/64"
        return str(address)
    except Exception:  # must never raise: a bad header cannot break the request
        return None


def _header_values(request: Request, name: str) -> list[str]:
    wanted = name.lower().encode("latin-1")
    return [
        value.decode("latin-1") for key, value in request.scope.get("headers", []) if key == wanted
    ]


def _forwarded_candidate(request: Request, header: str, trusted_proxies: int) -> str | None:
    if header:
        values = _header_values(request, header)
        return values[-1] if len(values) == 1 else None
    if trusted_proxies > 0:
        entries = [
            part.strip()
            for line in _header_values(request, "x-forwarded-for")
            for part in line.split(",")
        ]
        if len(entries) >= trusted_proxies:
            return entries[-trusted_proxies]
    return None


def client_key(
    request: Request,
    *,
    header: str | None = None,
    trusted_proxies: int | None = None,
) -> str:
    """Key identifying the calling client for rate and concurrency limits."""

    candidate = _forwarded_candidate(
        request,
        CLIENT_IP_HEADER if header is None else header.strip().lower(),
        TRUSTED_PROXY_COUNT if trusted_proxies is None else trusted_proxies,
    )
    if candidate is not None:
        key = normalize_ip(candidate)
        if key is not None:
            return key
    peer: Any = request.client
    host = peer.host if peer else ""
    return normalize_ip(host) or host or "unknown"
