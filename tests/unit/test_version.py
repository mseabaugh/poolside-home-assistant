"""Release metadata consistency tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.poolside.const import VERSION

pytestmark = pytest.mark.unit


def test_manifest_and_runtime_version_are_identical() -> None:
    """The package metadata and runtime constant use the same semantic version."""
    manifest = json.loads(
        (Path(__file__).parents[2] / "custom_components" / "poolside" / "manifest.json").read_text()
    )
    assert manifest["version"] == VERSION
    assert VERSION.count(".") == 2
    assert all(part.isdigit() for part in VERSION.split("."))
