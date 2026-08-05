"""Poolside transport boundary and confirmed cloud implementation."""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from time import monotonic
from typing import Any, Final, NoReturn, Protocol
from urllib.parse import urlparse
from uuid import uuid4

import aiohttp

from .const import API_URL, WS_URL
from .exceptions import AuthenticationError, CannotConnectError, ProtocolError, RemoteError
from .parser import decode_json_value, require_mapping

_LOGGER = logging.getLogger(__name__)
_HTTP_ERROR_STATUS = 400
_AUTH_FAILURES: Final = frozenset({401, 403})
_LOGIN_METHOD: Final = "User.login"
_TOKEN_FIELDS: Final = ("accessToken", "access_token", "token", "Token")
_VISIBLE_FAILURES: Final = frozenset({"authentication_error", "connection_error"})


def _log_completion(method: str, started: float, outcome: str, correlation_id: str) -> None:
    """Log only operation metadata that is safe for central collection."""
    duration_ms = round((monotonic() - started) * 1000)
    log_method = _LOGGER.warning if outcome in _VISIBLE_FAILURES else _LOGGER.debug
    log_method(
        "poolside_rpc correlation_id=%s method=%s outcome=%s duration_ms=%s",
        correlation_id,
        method,
        outcome,
        duration_ms,
    )


def _log_known_error(
    method: str,
    started: float,
    correlation_id: str,
    error: AuthenticationError | CannotConnectError | ProtocolError,
) -> NoReturn:
    """Log a safe outcome for a typed transport failure and preserve its exception."""
    if isinstance(error, AuthenticationError):
        outcome = "authentication_error"
    elif isinstance(error, CannotConnectError):
        outcome = "connection_error"
    else:
        outcome = "protocol_error"
    _log_completion(method, started, outcome, correlation_id)
    raise error


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
        except (AuthenticationError, CannotConnectError, ProtocolError) as err:
            _log_known_error(method, started, correlation_id, err)
        except (TimeoutError, aiohttp.ClientError) as err:
            _log_completion(method, started, "connection_error", correlation_id)
            raise CannotConnectError("Poolside request failed") from err

        mapping = require_mapping(payload, "JSON-RPC response")
        if "error" in mapping:
            _log_completion(method, started, "remote_error", correlation_id)
            raise RemoteError("Poolside returned a JSON-RPC error")
        if "result" not in mapping:
            _log_completion(method, started, "protocol_error", correlation_id)
            raise ProtocolError("Poolside response did not contain a result")
        _log_completion(method, started, "success", correlation_id)
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


async def async_login(
    session: aiohttp.ClientSession,
    username: str,
    password: str,
    endpoints: Endpoints | None = None,
) -> str:
    """Exchange Poolside credentials for a bearer token through ``User.login``."""
    if not username.strip() or not password:
        raise ValueError("Username and password must not be empty")

    resolved_endpoints = endpoints or Endpoints()
    trace_id = str(uuid4())
    correlation_id = trace_id.replace("-", "")[:12]
    request = {
        "id": str(uuid4()),
        "jsonrpc": "2.0",
        "method": _LOGIN_METHOD,
        "params": {"username": username.strip(), "password": password},
        "traceId": trace_id,
    }
    started = monotonic()
    payload = await _async_login_request(
        session, resolved_endpoints, request, started, correlation_id
    )
    return _parse_login_response(payload, started, correlation_id)


async def _async_login_request(
    session: aiohttp.ClientSession,
    endpoints: Endpoints,
    request: Mapping[str, Any],
    started: float,
    correlation_id: str,
) -> Any:
    """Execute the unauthenticated login request and return its decoded JSON body."""
    try:
        async with session.post(
            endpoints.api_url,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=request,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as response:
            if response.status in _AUTH_FAILURES:
                raise AuthenticationError("Poolside rejected the username or password")
            if response.status >= _HTTP_ERROR_STATUS:
                raise CannotConnectError("Poolside returned an HTTP failure during login")
            try:
                payload = await response.json(content_type=None)
            except (aiohttp.ContentTypeError, json.JSONDecodeError, UnicodeDecodeError) as err:
                raise ProtocolError("Poolside returned malformed login JSON") from err
    except (AuthenticationError, CannotConnectError, ProtocolError) as err:
        _log_known_error(_LOGIN_METHOD, started, correlation_id, err)
    except (TimeoutError, aiohttp.ClientError) as err:
        _log_completion(_LOGIN_METHOD, started, "connection_error", correlation_id)
        raise CannotConnectError("Poolside login request failed") from err
    return payload


def _parse_login_response(payload: Any, started: float, correlation_id: str) -> str:
    """Parse a login response and return only its bearer token."""
    mapping = require_mapping(payload, "Poolside login response")
    if "error" in mapping:
        error = mapping["error"]
        code = error.get("code") if isinstance(error, Mapping) else None
        if code in _AUTH_FAILURES:
            _log_completion(_LOGIN_METHOD, started, "authentication_error", correlation_id)
            raise AuthenticationError("Poolside rejected the username or password")
        _log_completion(_LOGIN_METHOD, started, "remote_error", correlation_id)
        raise RemoteError("Poolside returned a login error")
    if "result" not in mapping:
        _log_completion(_LOGIN_METHOD, started, "protocol_error", correlation_id)
        raise ProtocolError("Poolside login response did not contain a result")

    token = _extract_login_token(decode_json_value(mapping["result"]))
    if token is None:
        _log_completion(_LOGIN_METHOD, started, "protocol_error", correlation_id)
        raise ProtocolError("Poolside login did not return an access token")
    _log_completion(_LOGIN_METHOD, started, "success", correlation_id)
    return token


def _extract_login_token(result: Any) -> str | None:
    """Extract the bearer token without retaining or logging the submitted password."""
    if isinstance(result, str):
        token = result.strip()
        return token or None
    if not isinstance(result, Mapping):
        return None
    for field in _TOKEN_FIELDS:
        value = result.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
