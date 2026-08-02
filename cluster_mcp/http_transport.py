"""Authenticated Streamable HTTP transport helpers."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import secrets
import stat
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from mcp.server import MCPServer
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings as MCPAuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.types import ASGIApp, Receive, Scope, Send

from .config import HTTPSettings
from .errors import ConfigurationError

logger = logging.getLogger(__name__)


class EnvironmentBearerTokenVerifier(TokenVerifier):
    """Verify one opaque bearer token loaded from the server environment."""

    def __init__(self, *, token: str, principal: str, scopes: Sequence[str]) -> None:
        self._token = token
        self._principal = principal
        self._scopes = sorted(set(scopes))

    async def verify_token(self, token: str) -> AccessToken | None:
        if not secrets.compare_digest(token, self._token):
            return None
        return AccessToken(
            token=token,
            client_id=self._principal,
            subject=self._principal,
            scopes=self._scopes,
            claims={"auth_method": "http-bearer"},
        )


class ClientNetworkAllowlistMiddleware:
    """Reject direct HTTP clients outside configured IP networks."""

    def __init__(self, app: ASGIApp, networks: Sequence[str]) -> None:
        self.app = app
        self.networks = tuple(ipaddress.ip_network(value, strict=False) for value in networks)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and not self._allowed(scope.get("client")):
            logger.warning(
                "Rejected HTTP client outside configured network allowlist: %r", scope.get("client")
            )
            body = b'{"error":"client_network_denied"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 403,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send)

    def _allowed(self, client: object) -> bool:
        if not isinstance(client, (list, tuple)) or not client or not isinstance(client[0], str):
            return False
        try:
            address = ipaddress.ip_address(client[0])
        except ValueError:
            return False
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        return any(address in network for network in self.networks)


def load_http_token(settings: HTTPSettings) -> str:
    token = os.environ.get(settings.token_env_var)
    if token is None:
        raise ConfigurationError(
            f"HTTP bearer token environment variable {settings.token_env_var!r} is not set"
        )
    if len(token) < 32:
        raise ConfigurationError("HTTP bearer token must contain at least 32 characters")
    try:
        token.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ConfigurationError("HTTP bearer token must contain only ASCII characters") from exc
    if any(character.isspace() or character == "\x00" for character in token):
        raise ConfigurationError("HTTP bearer token may not contain whitespace or NUL bytes")
    return token


def validate_http_settings(settings: HTTPSettings) -> None:
    parsed = urlsplit(settings.public_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path != settings.path
    ):
        raise ConfigurationError(
            "http.public_url must be an absolute HTTP(S) URL ending at http.path"
        )

    tls_enabled = settings.tls_cert_file is not None and settings.tls_key_file is not None
    if tls_enabled != (parsed.scheme == "https"):
        raise ConfigurationError("HTTP TLS files and the public_url https scheme must agree")

    loopback = _is_loopback_host(settings.host)
    if not loopback and not tls_enabled:
        raise ConfigurationError("Non-loopback HTTP listeners require TLS")
    if not loopback and not settings.allowed_client_networks:
        raise ConfigurationError("Non-loopback HTTP listeners require an IP network allowlist")

    try:
        tuple(
            ipaddress.ip_network(value, strict=False) for value in settings.allowed_client_networks
        )
    except ValueError as exc:
        raise ConfigurationError(
            "http.allowed_client_networks contains an invalid network"
        ) from exc

    if settings.tls_cert_file is not None:
        _validate_regular_file(settings.tls_cert_file, private=False)
    if settings.tls_key_file is not None:
        _validate_regular_file(settings.tls_key_file, private=True)


def mcp_auth_settings(settings: HTTPSettings) -> MCPAuthSettings:
    parsed = urlsplit(settings.public_url)
    issuer_url = urlunsplit((parsed.scheme, parsed.netloc, "/", "", ""))
    return MCPAuthSettings(
        issuer_url=AnyHttpUrl(issuer_url),
        resource_server_url=AnyHttpUrl(settings.public_url),
        required_scopes=[],
    )


def transport_security_settings(settings: HTTPSettings) -> TransportSecuritySettings:
    parsed = urlsplit(settings.public_url)
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[parsed.netloc],
        allowed_origins=[origin],
    )


def run_http_server(mcp_server: MCPServer, settings: HTTPSettings) -> None:
    """Run an MCPServer Starlette app with TLS and a direct-client allowlist."""
    import uvicorn

    app = mcp_server.streamable_http_app(
        host=settings.host,
        streamable_http_path=settings.path,
        stateless_http=settings.stateless,
        json_response=settings.json_response,
        transport_security=transport_security_settings(settings),
    )
    app = ClientNetworkAllowlistMiddleware(app, settings.allowed_client_networks)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.host,
            port=settings.port,
            log_level="info",
            ssl_certfile=(str(settings.tls_cert_file) if settings.tls_cert_file else None),
            ssl_keyfile=(str(settings.tls_key_file) if settings.tls_key_file else None),
        )
    )
    asyncio.run(server.serve())


def _is_loopback_host(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_regular_file(path: Path, *, private: bool) -> None:
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ConfigurationError(f"HTTP TLS file does not exist: {path}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ConfigurationError(f"HTTP TLS path must be a regular file: {path}")
    if not os.access(path, os.R_OK):
        raise ConfigurationError(f"HTTP TLS file is not readable: {path}")
    if private:
        if metadata.st_uid != os.geteuid():
            raise ConfigurationError("HTTP TLS private key must be owned by the server user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise ConfigurationError("HTTP TLS private key permissions must be 0600")
