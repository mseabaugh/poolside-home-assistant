"""Shared deterministic test fixtures."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

import pytest

pytest_plugins = ["pytest_homeassistant_custom_component"]

_FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def user_config() -> dict[str, Any]:
    """Return a fresh synthetic discovery document."""
    return cast("dict[str, Any]", json.loads((_FIXTURES / "user_config.json").read_text()))


@pytest.fixture
def states_payload() -> dict[str, Any]:
    """Return a fresh synthetic state response."""
    return cast("dict[str, Any]", json.loads((_FIXTURES / "states.json").read_text()))


@pytest.fixture
def desired_payload() -> dict[str, Any]:
    """Return a fresh synthetic desired-state response."""
    return cast("dict[str, Any]", json.loads((_FIXTURES / "desired.json").read_text()))
