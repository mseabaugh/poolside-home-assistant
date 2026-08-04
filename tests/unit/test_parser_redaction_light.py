"""Unit coverage for parsing, redaction, and light conversion."""

from __future__ import annotations

import pytest

from custom_components.poolside.exceptions import ProtocolError
from custom_components.poolside.light_codec import (
    decode_rgb,
    encode_rgb,
    ha_brightness_to_poolside,
    poolside_brightness_to_ha,
)
from custom_components.poolside.parser import (
    decode_json_value,
    parse_state,
    require_mapping,
    unwrap_result,
)
from custom_components.poolside.redact import REDACTED, fingerprint, redact, redact_text

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        (12, 12),
        ("null", None),
        ("true", True),
        ("false", False),
        ("12", 12),
        ("12.5", 12.5),
        ("004", "004"),
        ('["a"]', ["a"]),
        ("Blue", "Blue"),
        ("NaN", "NaN"),
        ("Infinity", "Infinity"),
        ("1e999", "1e999"),
    ],
)
def test_parse_state(raw: object, expected: object) -> None:
    """State parsing is conservative across valid and invalid values."""
    assert parse_state(raw) == expected


def test_nested_json_and_required_mapping() -> None:
    """Nested responses decode at most twice and mappings require string keys."""
    assert decode_json_value('"{\\"answer\\":42}"') == {"answer": 42}
    assert decode_json_value("plain") == "plain"
    assert decode_json_value(4) == 4
    assert require_mapping('{"x":1}', "test") == {"x": 1}
    with pytest.raises(ProtocolError, match="Expected object"):
        require_mapping([], "test")
    with pytest.raises(ProtocolError, match="Expected object"):
        require_mapping({1: "bad"}, "test")


def test_unwrap_result() -> None:
    """JSON-RPC results unwrap while error and incomplete payloads fail closed."""
    assert unwrap_result({"result": '"true"'}) is True
    with pytest.raises(ProtocolError, match="error payload"):
        unwrap_result({"error": {"code": -1}})
    with pytest.raises(ProtocolError, match="did not contain"):
        unwrap_result({"jsonrpc": "2.0"})


def test_recursive_redaction() -> None:
    """Credentials, identity, location, network metadata, and nested values are removed."""
    uuid = "123e4567-e89b-42d3-a456-426614174000"
    jwt = "eyJabcdefghijk.abcdefghijk.abcdefghijk"
    text = f"Bearer secret.value user@example.com {uuid} 192.168.1.44 {jwt}"
    redacted_text = redact_text(text)
    assert "secret" not in redacted_text
    assert "example.com" not in redacted_text
    assert uuid not in redacted_text
    assert "192.168" not in redacted_text
    assert jwt not in redacted_text
    assert redacted_text.count(REDACTED) >= 5

    value = {
        "access_token": "secret",
        "Nested": [{"Site-UUID": uuid, "safe": text}, 1],
        "Tuple": ("plain", uuid),
    }
    result = redact(value)
    assert result["access_token"] == REDACTED
    assert result["Nested"][0]["Site-UUID"] == REDACTED
    assert result["Nested"][1] == 1
    assert result["Tuple"] == ("plain", REDACTED)
    assert redact(3) == 3


def test_fingerprint_is_stable_and_order_independent() -> None:
    """Account deduplication never stores the source identifiers."""
    first = fingerprint("site-b", "site-a")
    assert first == fingerprint("site-a", "site-b")
    assert "site" not in first
    assert len(first) == 64


@pytest.mark.parametrize("value", [-1, 256])
def test_ha_brightness_rejects_out_of_range(value: int) -> None:
    """Home Assistant brightness boundaries fail closed."""
    with pytest.raises(ValueError, match="Brightness"):
        ha_brightness_to_poolside(value)


@pytest.mark.parametrize("value", [-1, 101])
def test_poolside_brightness_rejects_out_of_range(value: int) -> None:
    """Poolside brightness boundaries fail closed."""
    with pytest.raises(ValueError, match="Brightness"):
        poolside_brightness_to_ha(value)


def test_brightness_round_trip_and_rgb_codec() -> None:
    """Confirmed light encodings round-trip at their documented scales."""
    assert ha_brightness_to_poolside(0) == 0
    assert ha_brightness_to_poolside(255) == 100
    assert poolside_brightness_to_ha(0) == 0
    assert poolside_brightness_to_ha(100) == 255
    encoded = encode_rgb((255, 61, 58))
    assert encoded == '#[{"duration":0,"RGB":"255|61|58","fadeIn":0}]'
    assert decode_rgb(encoded) == (255, 61, 58)


@pytest.mark.parametrize(
    "rgb",
    [
        (),
        (0, 0),
        (0, 0, 0, 0),
        (True, 0, 0),
        (-1, 0, 0),
        (256, 0, 0),
        (1.5, 0, 0),
    ],
)
def test_encode_rgb_rejects_invalid_channels(rgb: tuple[object, ...]) -> None:
    """RGB serialization rejects ambiguous or invalid values."""
    with pytest.raises(ValueError, match="RGB"):
        encode_rgb(rgb)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "value",
    [
        None,
        "Blue",
        "#[bad",
        "#[]",
        '#["bad"]',
        '#[{"NoRGB":"1|2|3"}]',
        '#[{"RGB":1}]',
        '#[{"RGB":"1|2"}]',
        '#[{"RGB":"1|2|999"}]',
        '#[{"RGB":"x|2|3"}]',
    ],
)
def test_decode_rgb_rejects_unknown_formats(value: object) -> None:
    """Unknown light values never become misleading Home Assistant colors."""
    assert decode_rgb(value) is None
