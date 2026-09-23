from __future__ import annotations

import json
import socket

import pytest

from ts_agent.email import delivery
from ts_agent.email.errors import NotificationError


def test_smtp_connection_uses_ipv4_candidates_and_one_timeout_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """A dead IPv6 route must not delay or prevent an IPv4 SMTP connection."""

    getaddrinfo_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    connected: list[tuple[str, int]] = []
    timeouts: list[float] = []
    monotonic_values = iter((100.0, 100.25))

    def fake_getaddrinfo(*args: object, **kwargs: object) -> list[tuple[object, ...]]:
        getaddrinfo_calls.append((args, kwargs))
        return [
            (socket.AF_INET6, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("2001:db8::5", 465, 0, 0)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.5", 465)),
        ]

    class FakeSocket:
        def __init__(self, family: int, socktype: int, proto: int) -> None:
            assert family == socket.AF_INET
            assert socktype == socket.SOCK_STREAM
            assert proto == socket.IPPROTO_TCP

        def settimeout(self, value: float) -> None:
            timeouts.append(value)

        def connect(self, address: tuple[str, int]) -> None:
            connected.append(address)

        def close(self) -> None:
            pass

    monkeypatch.setattr(delivery.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(delivery.socket, "socket", FakeSocket)
    monkeypatch.setattr(delivery.time, "monotonic", lambda: next(monotonic_values))

    result = delivery._create_ipv4_connection("smtp.qq.com", 465, 1.0)

    assert result.__class__ is FakeSocket
    assert connected == [("192.0.2.5", 465)]
    assert timeouts == [pytest.approx(0.75)]
    assert getaddrinfo_calls == [
        (
            ("smtp.qq.com", 465),
            {
                "family": socket.AF_INET,
                "type": socket.SOCK_STREAM,
                "proto": socket.IPPROTO_TCP,
            },
        ),
    ]


def test_smtp_connection_does_not_reset_timeout_for_each_ipv4_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    timeouts: list[float] = []
    closed = 0
    monotonic_values = iter((10.0, 10.2, 10.8))

    monkeypatch.setattr(
        delivery.socket,
        "getaddrinfo",
        lambda *args, **kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.10", 465)),
            (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("192.0.2.11", 465)),
        ],
    )

    class FakeSocket:
        def settimeout(self, value: float) -> None:
            timeouts.append(value)

        def connect(self, address: tuple[str, int]) -> None:
            raise OSError(f"unreachable {address[0]}")

        def close(self) -> None:
            nonlocal closed
            closed += 1

    monkeypatch.setattr(delivery.socket, "socket", lambda *args: FakeSocket())
    monkeypatch.setattr(delivery.time, "monotonic", lambda: next(monotonic_values))

    with pytest.raises(OSError, match="unreachable 192.0.2.11"):
        delivery._create_ipv4_connection("smtp.qq.com", 465, 1.0)

    assert timeouts == [pytest.approx(0.8), pytest.approx(0.2)]
    assert closed == 2


def test_interrupted_sending_receipt_is_reconciled_to_unknown(tmp_path) -> None:
    receipt_ref = "reports/email/deliveries/" + "a" * 64 + ".json"
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps({
        "schema_version": delivery.RECEIPT_SCHEMA,
        "state": "sending",
        "created_at": "2026-09-23T00:00:00+00:00",
        "notification_digest": "sha256:" + "b" * 64,
        "event": "progress",
        "subject": "Progress",
        "provider": "smtp",
        "workspace_id": "ws_" + "c" * 24,
        "workspace_revision": "rev_1",
        "report_artifacts": [],
    }) + "\n", encoding="utf-8")

    with pytest.raises(NotificationError) as captured:
        delivery._existing_delivery_result(receipt_ref, receipt_path, "sha256:" + "b" * 64)

    assert captured.value.code == "NOTIFICATION_DELIVERY_AMBIGUOUS"
    assert captured.value.state == "unknown"
    assert captured.value.receipt_ref == receipt_ref
    reconciled = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert reconciled["state"] == "unknown"
    assert reconciled["error_class"] == "delivery_ambiguous"


def test_ssl_smtp_client_preserves_hostname_for_tls_server_name(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSocket:
        def close(self) -> None:
            pass

    class FakeContext:
        def __init__(self) -> None:
            self.calls: list[tuple[object, str]] = []

        def wrap_socket(self, value: object, *, server_hostname: str) -> str:
            self.calls.append((value, server_hostname))
            return "wrapped-socket"

    plain = FakeSocket()
    context = FakeContext()
    monkeypatch.setattr(delivery, "_create_ipv4_connection", lambda *args: plain)
    client_type = delivery._smtp_client_class(ssl_enabled=True)
    client = object.__new__(client_type)
    client.debuglevel = 0
    client.source_address = None
    client.context = context
    client._host = "smtp.qq.com"

    result = client._get_socket("smtp.qq.com", 465, 5)

    assert result == "wrapped-socket"
    assert context.calls == [(plain, "smtp.qq.com")]
