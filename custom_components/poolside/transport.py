"""Poolside transport boundary and confirmed cloud implementation."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, Final, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp

from .const import API_URL, WS_URL
from .exceptions import AuthenticationError, CannotConnectError, ProtocolError, RemoteError
from .parser import decode_json_value, require_mapping

_LOGGER = logging.getLogger(__name__)
_HTTP_ERROR_STATUS = 400
_AUTH_FAILURES: Final = frozenset({401, 403})


class Transport(Protocol):
    """Injectable request/push boundary used by the typed client."""

    async def async_rpc(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Execute one JSON-RPC operation."""

    def async_messages(self) -> AsyncIterator[Mapping[str, Any]]:
        """Yield WebSocket messages until disconnected."""


@dataclass(frozen=True, slots=True)
class Endpoints:
    """Validated HTTP and WebSocket endpoints."""

    api_url: str = API_URL
    ws_url: str = WS_URL


def resolve_endpoints(environment: Mapping[str, str] | None = None) -> Endpoints:
    """Resolve fixed production endpoints or explicit process-level test endpoints."""
    values = os.environ if environment is None else environment
    if values.get("POOLSIDE_TEST_MODE") != "1":
        return Endpoints()
    endpoints = Endpoints(
        api_url=values.get("POOLSIDE_API_URL", API_URL),
        ws_url=values.get("POOLSIDE_WS_URL", WS_URL),
    )
    api_scheme = urlparse(endpoints.api_url).scheme
    ws_scheme = urlparse(endpoints.ws_url).scheme
    if api_scheme not in {"http", "https"} or ws_scheme not in {"ws", "wss"}:
        raise ValueError("Test endpoints must use HTTP or WebSocket schemes")
    return endpoints


class CloudTransport:
    """JSON-RPC over Poolside HTTPS and WebSocket cloud endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        endpoints: Endpoints | None = None,
        *,
        websocket_heartbeat: float | None = 30,
    ) -> None:
        """Initialize a transport without validating or logging the credential."""
        if not access_token.strip():
            raise ValueError("Access token must not be empty")
        self._session = session
        self._access_token = access_token
        self._endpoints = endpoints or Endpoints()
        self._websocket_heartbeat = websocket_heartbeat

    @property
    def _headers(self) -> dict[str, str]:
        """Build request headers at call time so they never enter object representations."""
        return {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }

    async def async_rpc(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Execute one JSON-RPC operation with body-free observability."""
        trace_id = str(uuid4())
        correlation_id = trace_id.replace("-", "")[:12]
        request: dict[str, Any] = {
            "id": str(uuid4()),
            "jsonrpc": "2.0",
            "method": method,
            "traceId": trace_id,
        }
        if params is not None:
            request["params"] = dict(params)
        started = monotonic()
        try:
            async with self._session.post(
                self._endpoints.api_url,
                headers=self._headers,
                json=request,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status in _AUTH_FAILURES:
                    raise AuthenticationError("Poolside rejected the access token")
                if response.status >= _HTTP_ERROR_STATUS:
                    raise CannotConnectError("Poolside returned an HTTP failure")
                try:
                    payload = await response.json(content_type=None)
                except (aiohttp.ContentTypeError, json.JSONDecodeError, UnicodeDecodeError) as err:
                    raise ProtocolError("Poolside returned malformed JSON") from err
        except AuthenticationError:
            self._log_completion(method, started, "authentication_error", correlation_id)
            raise
        except (TimeoutError, aiohttp.ClientError) as err:
            self._log_completion(method, started, "connection_error", correlation_id)
            raise CannotConnectError("Poolside request failed") from err

        mapping = require_mapping(payload, "JSON-RPC response")
        if "error" in mapping:
            self._log_completion(method, started, "remote_error", correlation_id)
            raise RemoteError("Poolside returned a JSON-RPC error")
        if "result" not in mapping:
            self._log_completion(method, started, "protocol_error", correlation_id)
            raise ProtocolError("Poolside response did not contain a result")
        self._log_completion(method, started, "success", correlation_id)
        return decode_json_value(mapping["result"])

    async def async_messages(self) -> AsyncIterator[Mapping[str, Any]]:
        """Yield validated server push objects from one WebSocket connection."""
        try:
            async with self._session.ws_connect(
                self._endpoints.ws_url,
                headers=self._headers,
                heartbeat=self._websocket_heartbeat,
                timeout=aiohttp.ClientWSTimeout(ws_receive=None, ws_close=10),
            ) as websocket:
                async for message in websocket:
                    if message.type is aiohttp.WSMsgType.TEXT:
                        try:
                            payload = json.loads(message.data)
                        except (json.JSONDecodeError, TypeError) as err:
                            raise ProtocolError(
                                "Poolside WebSocket returned malformed JSON"
                            ) from err
                        yield require_mapping(payload, "WebSocket message")
                    elif message.type is aiohttp.WSMsgType.ERROR:
                        raise CannotConnectError("Poolside WebSocket failed")
                    elif message.type in {
                        aiohttp.WSMsgType.CLOSE,
                        aiohttp.WSMsgType.CLOSED,
                        aiohttp.WSMsgType.CLOSING,
                    }:
                        return
        except AuthenticationError, CannotConnectError, ProtocolError:
            raise
        except aiohttp.WSServerHandshakeError as err:
            if err.status in _AUTH_FAILURES:
                raise AuthenticationError("Poolside rejected the access token") from err
            raise CannotConnectError("Poolside WebSocket handshake failed") from err
        except (TimeoutError, aiohttp.ClientError) as err:
            raise CannotConnectError("Poolside WebSocket connection failed") from err

    @staticmethod
    def _log_completion(method: str, started: float, outcome: str, correlation_id: str) -> None:
        """Log only operation metadata that is safe for central collection."""
        duration_ms = round((monotonic() - started) * 1000)
        _LOGGER.debug(
            "poolside_rpc correlation_id=%s method=%s outcome=%s duration_ms=%s",
            correlation_id,
            method,
            outcome,
            duration_ms,
        )
