"""Home Assistant integration fixtures with injected external resources."""

from __future__ import annotations

from typing import Any

import pytest
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolside.client import PoolsideClient
from custom_components.poolside.const import DOMAIN
from tests.fakes import FakeTransport


@pytest.fixture(autouse=True)
def _enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading this repository's custom integration."""


@pytest.fixture
def fake_transport(
    user_config: dict[str, Any],
    states_payload: dict[str, Any],
    desired_payload: dict[str, Any],
) -> FakeTransport:
    """Provide complete synthetic account responses."""
    return FakeTransport(
        {
            "Site.getDesiredState": desired_payload,
            "Site.getStates": states_payload,
            "Site.getAllConfig": {},
            "Site.setDesiredState2": True,
            "Site.setTheme": True,
            "User.getConfig": user_config,
            "ping": True,
        }
    )


@pytest.fixture
def fake_client(fake_transport: FakeTransport) -> PoolsideClient:
    """Provide the typed client with a fake external boundary."""
    return PoolsideClient(fake_transport)


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """Create an unloaded Poolside config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Poolside",
        data={CONF_ACCESS_TOKEN: "synthetic-token", "transport": "cloud"},
        unique_id="synthetic-account",
    )
    entry.add_to_hass(hass)
    return entry
