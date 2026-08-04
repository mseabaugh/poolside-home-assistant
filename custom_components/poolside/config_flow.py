"""UI configuration and reauthentication for Poolside."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import CONF_ACCESS_TOKEN
from homeassistant.helpers import selector

from .const import DOMAIN, NAME, TRANSPORT_CLOUD
from .exceptions import AuthenticationError, CannotConnectError, PoolsideError
from .factory import create_client

_LOGGER = logging.getLogger(__name__)

_TOKEN_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_ACCESS_TOKEN): selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    }
)


async def async_validate_token(flow: PoolsideConfigFlow, token: str) -> str:
    """Validate through injected Home Assistant resources and return an account fingerprint."""
    return await create_client(flow.hass, token).async_validate()


class PoolsideConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Manage Poolside config entries."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Create an entry from a manually obtained access token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_ACCESS_TOKEN]).strip()
            try:
                account_id = await async_validate_token(self, token)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except PoolsideError:
                _LOGGER.exception("Poolside configuration validation failed")
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(account_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=NAME,
                    data={CONF_ACCESS_TOKEN: token, "transport": TRANSPORT_CLOUD},
                )
        return self.async_show_form(step_id="user", data_schema=_TOKEN_SCHEMA, errors=errors)

    async def async_step_reauth(self, _entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after an authentication failure."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace the rejected credential and reload the existing entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            token = str(user_input[CONF_ACCESS_TOKEN]).strip()
            try:
                await async_validate_token(self, token)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except CannotConnectError:
                errors["base"] = "cannot_connect"
            except PoolsideError:
                _LOGGER.exception("Poolside reauthentication validation failed")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_ACCESS_TOKEN: token},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_TOKEN_SCHEMA,
            errors=errors,
        )
