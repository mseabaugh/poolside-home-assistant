"""Injected external-resource fakes used only by tests."""

from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from copy import deepcopy
from typing import Any

from custom_components.poolside.transport import Transport


class FakeTransport(Transport):
    """Deterministic in-memory transport with call recording."""

    def __init__(
        self,
        responses: Mapping[str, Any] | None = None,
        messages: Sequence[Mapping[str, Any]] | None = None,
    ) -> None:
        """Initialize with copied synthetic responses."""
        self.responses = dict(responses or {})
        self.messages = list(messages or [])
        self.calls: list[tuple[str, Mapping[str, Any] | None]] = []

    async def async_rpc(self, method: str, params: Mapping[str, Any] | None = None) -> Any:
        """Record and return or raise the configured response."""
        self.calls.append((method, deepcopy(params)))
        response = self.responses[method]
        if isinstance(response, Exception):
            raise response
        return deepcopy(response)

    async def async_messages(self) -> AsyncIterator[Mapping[str, Any]]:
        """Yield configured synthetic messages."""
        for message in self.messages:
            yield deepcopy(message)
