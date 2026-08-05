"""End-to-end application tests against a real synthetic HTTP/WebSocket service."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Mapping
from typing import Any, cast

import aiohttp
import pytest

from custom_components.poolside.client import PoolsideClient
from custom_components.poolside.exceptions import (
    AuthenticationError,
    CannotConnectError,
    RemoteError,
)
from custom_components.poolside.transport import CloudTransport, Endpoints, async_login
from tests.e2e.fake_poolside import (
    SYNTHETIC_PASSWORD,
    SYNTHETIC_TOKEN,
    SYNTHETIC_USERNAME,
    FakePoolsideService,
)

pytestmark = pytest.mark.e2e


async def test_real_http_websocket_read_write_and_push(
    aiohttp_server: Any, socket_enabled: None
) -> None:
    """Real I/O traverses transport, client, safety, fake server, and push confirmation."""
    service = FakePoolsideService()
    server = await aiohttp_server(service.application())
    api_url = str(server.make_url("/api/jsonrpc/v1"))
    ws_url = str(server.make_url("/websocket")).replace("http://", "ws://", 1)

    async with aiohttp.ClientSession() as session:
        endpoints = Endpoints(api_url, ws_url)
        assert (
            await async_login(session, SYNTHETIC_USERNAME, SYNTHETIC_PASSWORD, endpoints)
            == SYNTHETIC_TOKEN
        )
        transport = CloudTransport(
            session,
            SYNTHETIC_TOKEN,
            endpoints,
            websocket_heartbeat=None,
        )
        client = PoolsideClient(transport)
        assert await client.async_validate()
        data = await client.async_load()
        site = data.sites["site-alpha"]
        messages = transport.async_messages()
        assert (await anext(messages))["method"] == "Connection.activate"

        await client.async_set_control(site, "filter-one", {"Status": "OFF"})
        assert (await anext(messages))["method"] == "Site.setDesiredState"
        filter_state = next(
            row for row in service.desired["DesiredStates"] if row["ControlUUID"] == "filter-one"
        )
        assert filter_state["Status"] == "OFF"

        await client.async_activate_theme(site, "theme-calm")
        assert (await anext(messages))["method"] == "Device.setConfig"
        assert next(
            theme for theme in service.config["Sites"][0]["Themes"] if theme["UUID"] == "theme-calm"
        )["isWorking"]
        await cast("AsyncGenerator[Mapping[str, Any]]", messages).aclose()

        with pytest.raises(RemoteError, match="JSON-RPC"):
            await transport.async_rpc("Unsupported.method")
    await asyncio.sleep(0)


async def test_real_service_rejects_invalid_credentials(
    aiohttp_server: Any, socket_enabled: None
) -> None:
    """Authentication is enforced across the real HTTP boundary."""
    service = FakePoolsideService()
    server = await aiohttp_server(service.application())
    api_url = str(server.make_url("/api/jsonrpc/v1"))
    ws_url = str(server.make_url("/websocket")).replace("http://", "ws://", 1)
    async with aiohttp.ClientSession() as session:
        with pytest.raises(AuthenticationError):
            await async_login(session, "wrong-user", "wrong-password", Endpoints(api_url, ws_url))
        transport = CloudTransport(session, "wrong-token", Endpoints(api_url, ws_url))
        with pytest.raises(AuthenticationError, match="rejected"):
            await transport.async_rpc("ping")
        with pytest.raises(AuthenticationError):
            await anext(transport.async_messages())
        missing = CloudTransport(
            session,
            SYNTHETIC_TOKEN,
            Endpoints(api_url, str(server.make_url("/missing")).replace("http://", "ws://", 1)),
        )
        with pytest.raises(CannotConnectError, match="handshake"):
            await anext(missing.async_messages())
