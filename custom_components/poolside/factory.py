"""Production dependency assembly for the Poolside integration."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .client import PoolsideClient
from .transport import CloudTransport, resolve_endpoints
from .transport import async_login as async_login_transport


def create_client(hass: HomeAssistant, access_token: str) -> PoolsideClient:
    """Assemble the production client from Home Assistant-owned resources."""
    session = async_get_clientsession(hass)
    transport = CloudTransport(session, access_token, resolve_endpoints())
    return PoolsideClient(transport)


async def async_login(hass: HomeAssistant, username: str, password: str) -> str:
    """Exchange user credentials through Home Assistant's shared HTTP session."""
    session = async_get_clientsession(hass)
    return await async_login_transport(session, username, password, resolve_endpoints())
