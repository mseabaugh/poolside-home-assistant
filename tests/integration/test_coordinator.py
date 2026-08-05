"""Integration tests for coordinator failure translation and push lifecycle."""

from __future__ import annotations

from collections.abc import AsyncIterator, Coroutine
from typing import Any
from unittest.mock import AsyncMock, Mock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poolside.coordinator import PoolsideCoordinator
from custom_components.poolside.exceptions import (
    AuthenticationError,
    CannotConnectError,
    ProtocolError,
)
from custom_components.poolside.models import PoolsideData

pytestmark = pytest.mark.integration


class LoadClient:
    """Injected client that returns or raises one configured load result."""

    def __init__(self, result: PoolsideData | Exception) -> None:
        self.result = result

    async def async_load(self) -> PoolsideData:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result

    async def async_ping(self) -> bool:
        """Return a healthy heartbeat for coordinator lifecycle tests."""
        return True


class PushClient(LoadClient):
    """Scripted push client that exercises normal, reconnect, and auth paths."""

    def __init__(self) -> None:
        super().__init__(PoolsideData())
        self.calls = 0

    async def async_push_messages(self) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        self.calls += 1
        if self.calls == 1:
            yield "Site.setStates", {}
            yield "Connection.activate", {}
            yield "Unknown.push", {}
            return
        if self.calls == 2:
            raise CannotConnectError("synthetic")
        raise AuthenticationError("synthetic")


class HeartbeatClient(LoadClient):
    """Scripted heartbeat client for success, retry, and authentication paths."""

    def __init__(self, heartbeat_error: Exception | None = None) -> None:
        super().__init__(PoolsideData())
        self.heartbeat_error = heartbeat_error
        self.heartbeat_calls = 0

    async def async_ping(self) -> bool:
        self.heartbeat_calls += 1
        if self.heartbeat_error is not None:
            raise self.heartbeat_error
        return True


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (AuthenticationError("synthetic"), ConfigEntryAuthFailed),
        (CannotConnectError("synthetic"), UpdateFailed),
        (ProtocolError("synthetic"), UpdateFailed),
    ],
)
async def test_update_translates_domain_failures(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    failure: Exception,
    expected: type[Exception],
) -> None:
    """Authentication and availability failures map to Home Assistant contracts."""
    coordinator = PoolsideCoordinator(hass, config_entry, LoadClient(failure))  # type: ignore[arg-type]
    with pytest.raises(expected):
        await coordinator._async_update_data()
    await coordinator.async_shutdown()


async def test_update_logs_safe_http_failure_metadata(
    hass: HomeAssistant, config_entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    """Refresh diagnostics expose status metadata without response contents."""
    failure = CannotConnectError("synthetic", status=502, content_type="text/html")
    coordinator = PoolsideCoordinator(hass, config_entry, LoadClient(failure))  # type: ignore[arg-type]
    with pytest.raises(UpdateFailed):
        await coordinator._async_update_data()
    assert "poolside_refresh outcome=failed" in caplog.text
    assert "status=502" in caplog.text
    assert "content_type=text/html" in caplog.text
    await coordinator.async_shutdown()


async def test_heartbeat_success_and_retryable_failure(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Heartbeats call ping and keep retryable failures out of reauthentication."""

    async def stop_after_wait(
        awaitable: Coroutine[Any, Any, Any],
        *,
        timeout: float,  # noqa: ASYNC109
    ) -> None:
        del timeout
        awaitable.close()
        coordinator._stopping.set()
        raise TimeoutError

    monkeypatch.setattr("custom_components.poolside.coordinator.asyncio.wait_for", stop_after_wait)
    client = HeartbeatClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient(CannotConnectError("synthetic"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient(ProtocolError("synthetic"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1

    client = HeartbeatClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]

    async def stop_after_ping() -> bool:
        coordinator._stopping.set()
        return True

    client.async_ping = stop_after_ping  # type: ignore[method-assign]
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 0


async def test_heartbeat_authentication_failure_starts_reauth(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
) -> None:
    """An expired heartbeat token starts HA reauthentication and stops the loop."""
    client = HeartbeatClient(AuthenticationError("expired"))
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    reauth = Mock()
    config_entry.async_start_reauth = reauth
    await coordinator._async_heartbeat_loop()
    assert client.heartbeat_calls == 1
    reauth.assert_called_once_with(hass)


async def test_push_reconnect_refresh_ignore_reauth_and_idempotent_start(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Push refreshes relevant events, backs off failures, and reauthenticates once."""
    client = PushClient()
    coordinator = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    refresh = AsyncMock()
    reauth = Mock()
    monkeypatch.setattr(coordinator, "async_request_refresh", refresh)
    monkeypatch.setattr(config_entry, "async_start_reauth", reauth)

    async def instant_timeout(
        awaitable: Coroutine[Any, Any, Any],
        *,
        timeout: float,  # noqa: ASYNC109
    ) -> None:
        del timeout
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr("custom_components.poolside.coordinator.asyncio.wait_for", instant_timeout)
    await coordinator._async_push_loop()
    refresh.assert_awaited_once()
    reauth.assert_called_once_with(hass)
    assert client.calls == 3

    coordinator._stopping.set()
    coordinator.start_push()
    task = coordinator._push_task
    heartbeat_task = coordinator._heartbeat_task
    coordinator.start_push()
    assert coordinator._push_task is task
    assert coordinator._heartbeat_task is heartbeat_task
    await coordinator.async_shutdown()
    await coordinator.async_shutdown()

    stopped = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]
    stopped._stopping.set()
    await stopped._async_push_loop()

    ending = PoolsideCoordinator(hass, config_entry, client)  # type: ignore[arg-type]

    async def stop_during_stream() -> AsyncIterator[tuple[str, dict[str, Any]]]:
        ending._stopping.set()
        if ending._stopping.is_set():
            return
        yield "unreachable", {}

    monkeypatch.setattr(client, "async_push_messages", stop_during_stream)
    await ending._async_push_loop()
