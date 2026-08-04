"""Unit coverage for the cloud transport boundary."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import aiohttp
import pytest

from custom_components.poolside.const import API_URL, WS_URL
from custom_components.poolside.exceptions import (
    AuthenticationError,
    CannotConnectError,
    ProtocolError,
    RemoteError,
)
from custom_components.poolside.transport import CloudTransport, Endpoints, resolve_endpoints

pytestmark = pytest.mark.unit


class FakeResponse:
    """Async response context with configurable JSON behavior."""

    def __init__(self, status: int, payload: Any) -> None:
        self.status = status
        self.payload = payload

    async def __aenter__(self) -> FakeResponse:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self, **_kwargs: object) -> Any:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class FakeWebSocket:
    """Async WebSocket context and message iterator."""

    def __init__(self, messages: list[Any], enter_error: Exception | None = None) -> None:
        self.messages = messages
        self.enter_error = enter_error

    async def __aenter__(self) -> FakeWebSocket:
        if self.enter_error is not None:
            raise self.enter_error
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[Any]:
        for message in self.messages:
            yield message


class FakeSession:
    """Minimal aiohttp session fake injected into CloudTransport."""

    def __init__(
        self,
        post_value: FakeResponse | Exception | None = None,
        websocket: FakeWebSocket | Exception | None = None,
    ) -> None:
        self.post_value = post_value
        self.websocket = websocket
        self.post_calls: list[dict[str, Any]] = []
        self.ws_calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> FakeResponse:
        self.post_calls.append({"url": url, **kwargs})
        if isinstance(self.post_value, Exception):
            raise self.post_value
        assert self.post_value is not None
        return self.post_value

    def ws_connect(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.ws_calls.append({"url": url, **kwargs})
        if isinstance(self.websocket, Exception):
            raise self.websocket
        assert self.websocket is not None
        return self.websocket


def _transport(session: FakeSession) -> CloudTransport:
    """Construct with deliberately synthetic endpoints."""
    return CloudTransport(
        session,  # type: ignore[arg-type]
        "synthetic-token",
        Endpoints("https://synthetic.invalid/rpc", "wss://synthetic.invalid/ws"),
    )


def test_endpoint_resolution_is_production_fixed_and_test_explicit() -> None:
    """Environment values cannot redirect production traffic without explicit test mode."""
    assert resolve_endpoints({"POOLSIDE_API_URL": "http://ignored"}) == Endpoints(API_URL, WS_URL)
    assert resolve_endpoints(
        {
            "POOLSIDE_TEST_MODE": "1",
            "POOLSIDE_API_URL": "http://fake:8080/rpc",
            "POOLSIDE_WS_URL": "ws://fake:8080/ws",
        }
    ) == Endpoints("http://fake:8080/rpc", "ws://fake:8080/ws")
    assert resolve_endpoints({"POOLSIDE_TEST_MODE": "1"}) == Endpoints()
    with pytest.raises(ValueError, match="HTTP or WebSocket"):
        resolve_endpoints(
            {
                "POOLSIDE_TEST_MODE": "1",
                "POOLSIDE_API_URL": "file:///tmp/test",
                "POOLSIDE_WS_URL": "ws://fake/ws",
            }
        )
    with pytest.raises(ValueError, match="HTTP or WebSocket"):
        resolve_endpoints(
            {
                "POOLSIDE_TEST_MODE": "1",
                "POOLSIDE_API_URL": "http://fake/rpc",
                "POOLSIDE_WS_URL": "file:///tmp/test",
            }
        )


def test_transport_rejects_empty_token() -> None:
    """An empty credential never reaches a remote service."""
    with pytest.raises(ValueError, match="must not be empty"):
        CloudTransport(FakeSession(), " ")  # type: ignore[arg-type]


async def test_rpc_success_and_request_metadata(caplog: pytest.LogCaptureFixture) -> None:
    """RPC success sends required metadata and logs no body or credential."""
    session = FakeSession(FakeResponse(200, {"result": '"{\\"answer\\":42}"'}))
    transport = _transport(session)
    with caplog.at_level(logging.DEBUG):
        assert await transport.async_rpc("Synthetic.read", {"safe": True}) == {"answer": 42}
    call = session.post_calls[0]
    assert call["url"] == "https://synthetic.invalid/rpc"
    assert call["headers"]["Authorization"] == "Bearer synthetic-token"
    assert call["json"]["method"] == "Synthetic.read"
    assert call["json"]["params"] == {"safe": True}
    assert call["json"]["id"]
    assert call["json"]["traceId"]
    assert "synthetic-token" not in caplog.text
    assert "safe" not in caplog.text
    assert "outcome=success" in caplog.text

    session = FakeSession(FakeResponse(200, {"result": True}))
    assert await _transport(session).async_rpc("ping") is True
    assert "params" not in session.post_calls[0]["json"]


@pytest.mark.parametrize("status", [401, 403])
async def test_rpc_authentication_failures(status: int) -> None:
    """Authentication HTTP statuses surface distinctly for reauthentication."""
    with pytest.raises(AuthenticationError):
        await _transport(FakeSession(FakeResponse(status, {}))).async_rpc("ping")


async def test_rpc_http_connection_and_timeout_failures() -> None:
    """Remote HTTP, aiohttp, and timeout failures become safe connectivity errors."""
    with pytest.raises(CannotConnectError, match="HTTP"):
        await _transport(FakeSession(FakeResponse(500, {}))).async_rpc("ping")
    with pytest.raises(CannotConnectError, match="request failed"):
        await _transport(FakeSession(aiohttp.ClientError("synthetic"))).async_rpc("ping")
    with pytest.raises(CannotConnectError, match="request failed"):
        await _transport(FakeSession(TimeoutError())).async_rpc("ping")


async def test_rpc_protocol_and_remote_failures() -> None:
    """Malformed, remote-error, and incomplete responses fail with distinct contracts."""
    malformed = json.JSONDecodeError("synthetic", "x", 0)
    with pytest.raises(ProtocolError, match="malformed JSON"):
        await _transport(FakeSession(FakeResponse(200, malformed))).async_rpc("read")
    with pytest.raises(RemoteError, match="JSON-RPC error"):
        await _transport(FakeSession(FakeResponse(200, {"error": {"code": -1}}))).async_rpc("read")
    with pytest.raises(ProtocolError, match="did not contain"):
        await _transport(FakeSession(FakeResponse(200, {"jsonrpc": "2.0"}))).async_rpc("read")


async def test_websocket_yields_text_and_handles_close() -> None:
    """Valid push objects yield until a normal close frame."""
    messages = [
        SimpleNamespace(
            type=aiohttp.WSMsgType.TEXT,
            data='{"method":"Site.setStates","params":{}}',
        ),
        SimpleNamespace(type=aiohttp.WSMsgType.BINARY, data=b"ignored"),
        SimpleNamespace(type=aiohttp.WSMsgType.CLOSE, data=None),
    ]
    session = FakeSession(websocket=FakeWebSocket(messages))
    assert [item async for item in _transport(session).async_messages()] == [
        {"method": "Site.setStates", "params": {}}
    ]
    assert session.ws_calls[0]["url"] == "wss://synthetic.invalid/ws"
    assert session.ws_calls[0]["headers"]["Authorization"] == "Bearer synthetic-token"


@pytest.mark.parametrize(
    "close_type",
    [aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING],
)
async def test_websocket_normal_close_variants(close_type: aiohttp.WSMsgType) -> None:
    """All normal closing frame variants stop iteration."""
    websocket = FakeWebSocket([SimpleNamespace(type=close_type, data=None)])
    assert [
        item async for item in _transport(FakeSession(websocket=websocket)).async_messages()
    ] == []
    assert [
        item async for item in _transport(FakeSession(websocket=FakeWebSocket([]))).async_messages()
    ] == []


async def test_websocket_malformed_error_and_connection_failures() -> None:
    """Malformed frames, error frames, and session errors surface safely."""
    malformed = FakeWebSocket([SimpleNamespace(type=aiohttp.WSMsgType.TEXT, data="not-json")])
    with pytest.raises(ProtocolError, match="malformed JSON"):
        _ = [item async for item in _transport(FakeSession(websocket=malformed)).async_messages()]

    error = FakeWebSocket([SimpleNamespace(type=aiohttp.WSMsgType.ERROR, data=None)])
    with pytest.raises(CannotConnectError, match="failed"):
        _ = [item async for item in _transport(FakeSession(websocket=error)).async_messages()]

    for failure in (aiohttp.ClientError("synthetic"), TimeoutError()):
        with pytest.raises(CannotConnectError, match="connection failed"):
            _ = [item async for item in _transport(FakeSession(websocket=failure)).async_messages()]


async def test_websocket_preserves_expected_domain_failures() -> None:
    """Expected domain failures are not collapsed into generic connectivity errors."""
    for failure in (
        AuthenticationError("synthetic"),
        CannotConnectError("synthetic"),
        ProtocolError("synthetic"),
    ):
        websocket = FakeWebSocket([], enter_error=failure)
        with pytest.raises(type(failure), match="synthetic"):
            _ = [
                item async for item in _transport(FakeSession(websocket=websocket)).async_messages()
            ]
