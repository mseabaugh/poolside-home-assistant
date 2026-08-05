"""Integration tests for UI setup, duplicate prevention, and reauthentication."""

from __future__ import annotations

from unittest.mock import ANY, AsyncMock, Mock

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_ACCESS_TOKEN, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolside.config_flow import (
    PoolsideConfigFlow,
    async_login,
    async_validate_token,
)
from custom_components.poolside.const import DOMAIN
from custom_components.poolside.exceptions import (
    AuthenticationError,
    CannotConnectError,
    ProtocolError,
)

pytestmark = pytest.mark.integration


async def test_validation_uses_injected_home_assistant_client_factory(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The production validation seam delegates to the typed client created for HA."""
    client = AsyncMock()
    client.async_validate.return_value = "account-fingerprint"
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.create_client", lambda *_args: client
    )
    flow = PoolsideConfigFlow()
    flow.hass = hass
    assert await async_validate_token(flow, "synthetic-token") == "account-fingerprint"


async def test_login_uses_injected_home_assistant_factory(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Credential exchange delegates to the production factory seam."""
    session = object()
    get_session = Mock(return_value=session)
    login = AsyncMock(return_value="synthetic-token")
    monkeypatch.setattr("custom_components.poolside.factory.async_get_clientsession", get_session)
    monkeypatch.setattr("custom_components.poolside.factory.async_login_transport", login)
    flow = PoolsideConfigFlow()
    flow.hass = hass
    assert await async_login(flow, "synthetic-user", "synthetic-password") == "synthetic-token"
    get_session.assert_called_once_with(hass)
    login.assert_awaited_once_with(
        session,
        "synthetic-user",
        "synthetic-password",
        ANY,
    )


async def test_user_flow_creates_unique_entry(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Valid credentials create one cloud config entry while storing only the token."""
    login = AsyncMock(return_value="synthetic-token")
    validate = AsyncMock(return_value="account-fingerprint")
    monkeypatch.setattr("custom_components.poolside.config_flow.async_login", login)
    monkeypatch.setattr("custom_components.poolside.config_flow.async_validate_token", validate)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: " synthetic-user ", CONF_PASSWORD: "synthetic-password"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Poolside"
    assert result["data"] == {CONF_ACCESS_TOKEN: "synthetic-token", "transport": "cloud"}
    login.assert_awaited_once_with(ANY, "synthetic-user", "synthetic-password")
    validate.assert_awaited_once_with(ANY, "synthetic-token")


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AuthenticationError("synthetic"), "invalid_auth"),
        (CannotConnectError("synthetic"), "cannot_connect"),
        (ProtocolError("synthetic"), "unknown"),
    ],
)
async def test_user_flow_surfaces_common_failures(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    expected: str,
) -> None:
    """Expected auth, connectivity, and protocol failures remain user-actionable."""
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.async_login",
        AsyncMock(return_value="synthetic-token"),
    )
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.async_validate_token",
        AsyncMock(side_effect=failure),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_USERNAME: "synthetic-user", CONF_PASSWORD: "synthetic-password"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}


async def test_user_flow_surfaces_login_failure(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Rejected credentials are shown as an authentication error in Home Assistant."""
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.async_login",
        AsyncMock(side_effect=AuthenticationError("synthetic")),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "synthetic-user", CONF_PASSWORD: "synthetic-password"},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_duplicate_account_aborts(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The non-reversible account fingerprint prevents duplicate setup."""
    existing = MockConfigEntry(domain=DOMAIN, unique_id="same-account", data={})
    existing.add_to_hass(hass)
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.async_login",
        AsyncMock(return_value="synthetic-token"),
    )
    monkeypatch.setattr(
        "custom_components.poolside.config_flow.async_validate_token",
        AsyncMock(return_value="same-account"),
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_USER},
        data={CONF_USERNAME: "synthetic-user", CONF_PASSWORD: "synthetic-password"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reauthentication_success_and_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reauthentication exchanges credentials before replacing and reloading the token."""
    login = AsyncMock(return_value="replacement-token")
    validate = AsyncMock(return_value="synthetic-account")
    monkeypatch.setattr("custom_components.poolside.config_flow.async_login", login)
    monkeypatch.setattr("custom_components.poolside.config_flow.async_validate_token", validate)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": config_entry.entry_id,
        },
        data=dict(config_entry.data),
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {CONF_USERNAME: "replacement-user", CONF_PASSWORD: "replacement-password"},
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert config_entry.data[CONF_ACCESS_TOKEN] == "replacement-token"
    login.assert_awaited_once_with(ANY, "replacement-user", "replacement-password")

    for failure, expected in (
        (AuthenticationError("synthetic"), "invalid_auth"),
        (CannotConnectError("synthetic"), "cannot_connect"),
        (ProtocolError("synthetic"), "unknown"),
    ):
        monkeypatch.setattr(
            "custom_components.poolside.config_flow.async_login",
            AsyncMock(return_value="replacement-token"),
        )
        monkeypatch.setattr(
            "custom_components.poolside.config_flow.async_validate_token",
            AsyncMock(side_effect=failure),
        )
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": config_entry.entry_id,
            },
            data=dict(config_entry.data),
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_USERNAME: "bad-user", CONF_PASSWORD: "bad-password"},
        )
        assert result["type"] is FlowResultType.FORM
        assert result["errors"] == {"base": expected}
