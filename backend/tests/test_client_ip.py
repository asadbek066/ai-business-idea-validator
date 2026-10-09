import asyncio

import httpx
import pytest
from app import client_ip, main
from app.client_ip import client_key, normalize_ip
from app.main import SlidingWindowLimiter
from starlette.requests import Request


def make_request(peer: str | None, headers: dict[str, str] | None = None) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": raw,
            "client": (peer, 1234) if peer else None,
        }
    )


def test_default_ignores_spoofed_forwarding_headers() -> None:
    request = make_request("10.0.0.9", {"X-Forwarded-For": "1.2.3.4", "X-Real-IP": "5.6.7.8"})
    assert client_key(request) == "10.0.0.9"


def test_trusted_proxy_count_picks_nth_from_last_hop() -> None:
    request = make_request("10.0.0.9", {"X-Forwarded-For": "6.6.6.6, 203.0.113.7, 198.51.100.2"})
    # A client-supplied leftmost entry is never used.
    assert client_key(request, trusted_proxies=1) == "198.51.100.2"
    assert client_key(request, trusted_proxies=2) == "203.0.113.7"
    assert client_key(request, trusted_proxies=3) == "6.6.6.6"


def test_multiple_forwarded_for_lines_are_joined() -> None:
    request = make_request(None)
    request.scope["headers"] = [
        (b"x-forwarded-for", b"6.6.6.6"),
        (b"x-forwarded-for", b"203.0.113.7"),
    ]
    assert client_key(request, trusted_proxies=1) == "203.0.113.7"


def test_named_single_value_header() -> None:
    request = make_request("10.0.0.9", {"X-Real-IP": "203.0.113.7"})
    assert client_key(request, header="x-real-ip") == "203.0.113.7"


def test_named_header_with_duplicate_values_is_not_trusted() -> None:
    request = make_request(None)
    request.scope["client"] = ("10.0.0.9", 1)
    request.scope["headers"] = [(b"x-real-ip", b"1.1.1.1"), (b"x-real-ip", b"2.2.2.2")]
    assert client_key(request, header="x-real-ip") == "10.0.0.9"


@pytest.mark.parametrize(
    "value", ["garbage", "", "999.1.1.1", "1.2.3.4:80", "unknown", "<script>", "1.2.3"]
)
def test_unparseable_value_falls_back_to_socket_peer(value: str) -> None:
    request = make_request("10.0.0.9", {"X-Forwarded-For": value, "X-Real-IP": value})
    assert client_key(request, trusted_proxies=1) == "10.0.0.9"
    assert client_key(request, header="x-real-ip") == "10.0.0.9"


def test_too_few_forwarded_entries_falls_back_to_socket_peer() -> None:
    request = make_request("10.0.0.9", {"X-Forwarded-For": "203.0.113.7"})
    assert client_key(request, trusted_proxies=2) == "10.0.0.9"


def test_missing_peer_and_header_is_unknown() -> None:
    assert client_key(make_request(None)) == "unknown"


def test_ipv6_is_keyed_on_slash_64() -> None:
    a = normalize_ip("2001:db8:1:2:aaaa:bbbb:cccc:dddd")
    b = normalize_ip("2001:db8:1:2::1")
    c = normalize_ip("2001:db8:1:3::1")
    assert a == b == "2001:db8:1:2::/64"
    assert c != a


def test_ipv4_mapped_ipv6_maps_to_ipv4() -> None:
    assert normalize_ip("::ffff:203.0.113.7") == "203.0.113.7"


def test_socket_peer_ipv6_is_also_keyed_on_slash_64() -> None:
    request = make_request("2001:db8::5")
    assert client_key(request) == "2001:db8::/64"


def _statuses_for_spoofed_requests(monkeypatch, *, proxies: int) -> list[int]:
    monkeypatch.setattr(client_ip, "TRUSTED_PROXY_COUNT", proxies)
    monkeypatch.setattr(client_ip, "CLIENT_IP_HEADER", "")
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main, "VALIDATE_LIMITER", SlidingWindowLimiter(1, 60))

    async def ok(*args, **kwargs):
        return True, "openai"

    monkeypatch.setattr(main, "validate_provider", ok)
    body = {
        "ai_providers": {
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "k" * 12},
            "azure_openai": {"enabled": False},
            "gemini": {"enabled": False},
            "claude": {"enabled": False},
        }
    }

    async def scenario() -> list[int]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("10.0.0.9", 1)),
            base_url="http://testserver",
        ) as http:
            return [
                (
                    await http.post(
                        "/validate-provider", json=body, headers={"X-Forwarded-For": spoof}
                    )
                ).status_code
                for spoof in ("1.1.1.1", "2.2.2.2")
            ]

    return asyncio.run(scenario())


def test_rate_limit_ignores_spoofed_header_by_default(monkeypatch) -> None:
    # Same socket peer, rotating spoofed header: still one bucket.
    assert _statuses_for_spoofed_requests(monkeypatch, proxies=0) == [200, 429]


def test_rate_limit_uses_trusted_hop_when_configured(monkeypatch) -> None:
    # One trusted proxy: the last entry is the proxy-observed client, so
    # distinct clients get distinct buckets.
    assert _statuses_for_spoofed_requests(monkeypatch, proxies=1) == [200, 200]


ZONE_IDS = ["fe80::1%eth0", "fe80::1%1", "[fe80::1%eth0]", "2001:db8::1%25eth0", "::1%lo"]
HOSTILE = [
    "a" * 100_000,
    "1" * 5000 + "." + "1" * 5000,
    "1.2.3.4\x00",
    "\x00",
    "1.2.3.4\n5.6.7.8",
    "1.2.3.4\r\nX: y",
    "::",
    "::1",
    "0.0.0.0",
    "1.2.3.4:443",
    "[2001:db8::1]:443",
    "[::1]",
    "%",
    "::%",
    "١.٢.٣.٤",
    "1.2.3.4%eth0",
]


@pytest.mark.parametrize("value", ZONE_IDS)
def test_scoped_ipv6_is_rejected_and_never_raises(value: str) -> None:
    assert normalize_ip(value) is None
    request = make_request("10.0.0.9", {"X-Forwarded-For": value, "X-Real-IP": value})
    assert client_key(request, trusted_proxies=1) == "10.0.0.9"
    assert client_key(request, header="x-real-ip") == "10.0.0.9"


@pytest.mark.parametrize("value", HOSTILE)
def test_hostile_values_never_raise(value: str) -> None:
    result = normalize_ip(value)
    assert result is None or isinstance(result, str)
    # Headers arrive as latin-1 bytes; keep only values that can be encoded.
    try:
        raw = value.encode("latin-1")
    except UnicodeEncodeError:
        return
    request = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [(b"x-forwarded-for", raw), (b"x-real-ip", raw)],
            "client": ("10.0.0.9", 1),
        }
    )
    assert isinstance(client_key(request, trusted_proxies=1), str)
    assert isinstance(client_key(request, header="x-real-ip"), str)


def test_unspecified_and_loopback_are_valid_keys() -> None:
    assert normalize_ip("0.0.0.0") == "0.0.0.0"
    assert normalize_ip("::") == "::/64"
    assert normalize_ip("::1") == "::/64"


def test_normalize_ip_is_total_even_if_parsing_misbehaves(monkeypatch) -> None:
    def boom(_: str) -> None:
        raise RuntimeError("unexpected")

    monkeypatch.setattr(client_ip.ipaddress, "ip_address", boom)
    assert normalize_ip("1.2.3.4") is None


@pytest.mark.parametrize("mode", ["xff", "header"])
@pytest.mark.parametrize("value", ZONE_IDS)
def test_endpoint_does_not_500_on_scoped_address(monkeypatch, mode: str, value: str) -> None:
    monkeypatch.setattr(client_ip, "TRUSTED_PROXY_COUNT", 1 if mode == "xff" else 0)
    monkeypatch.setattr(client_ip, "CLIENT_IP_HEADER", "x-real-ip" if mode == "header" else "")
    monkeypatch.setattr(main, "RATE_LIMIT_ENABLED", True)
    monkeypatch.setattr(main, "VALIDATE_LIMITER", SlidingWindowLimiter(1, 60))

    async def ok(*args, **kwargs):
        return True, "openai"

    monkeypatch.setattr(main, "validate_provider", ok)
    body = {
        "ai_providers": {
            "openai": {"enabled": True, "model": "gpt-4o-mini", "api_key": "k" * 12},
            "azure_openai": {"enabled": False},
            "gemini": {"enabled": False},
            "claude": {"enabled": False},
        }
    }
    name = "X-Forwarded-For" if mode == "xff" else "X-Real-IP"

    async def scenario() -> list[int]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=main.app, client=("10.0.0.9", 1)),
            base_url="http://testserver",
        ) as http:
            return [
                (await http.post("/validate-provider", json=body, headers={name: value})).status_code
                for _ in range(2)
            ]

    # Falls back to the peer's single bucket: 200 then 429, never 500.
    assert asyncio.run(scenario()) == [200, 429]
