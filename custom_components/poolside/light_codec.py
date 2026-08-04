"""Poolside light value conversion."""

from __future__ import annotations

import json
from typing import Any

_HA_BRIGHTNESS_MAX = 255
_POOLSIDE_BRIGHTNESS_MAX = 100
_RGB_CHANNEL_COUNT = 3


def ha_brightness_to_poolside(brightness: int) -> int:
    """Map Home Assistant 0..255 brightness to Poolside 0..100."""
    if not 0 <= brightness <= _HA_BRIGHTNESS_MAX:
        raise ValueError("Brightness must be between 0 and 255")
    return round(brightness * _POOLSIDE_BRIGHTNESS_MAX / _HA_BRIGHTNESS_MAX)


def poolside_brightness_to_ha(brightness: float) -> int:
    """Map Poolside 0..100 brightness to Home Assistant 0..255."""
    if not 0 <= brightness <= _POOLSIDE_BRIGHTNESS_MAX:
        raise ValueError("Brightness must be between 0 and 100")
    return round(brightness * _HA_BRIGHTNESS_MAX / _POOLSIDE_BRIGHTNESS_MAX)


def encode_rgb(rgb: tuple[int, int, int]) -> str:
    """Encode a confirmed Poolside RGB light name."""
    if len(rgb) != _RGB_CHANNEL_COUNT or any(isinstance(channel, bool) for channel in rgb):
        raise ValueError("RGB requires three integer channels")
    if not all(isinstance(channel, int) and 0 <= channel <= _HA_BRIGHTNESS_MAX for channel in rgb):
        raise ValueError("RGB channels must be integers between 0 and 255")
    red, green, blue = rgb
    frames = [{"duration": 0, "RGB": f"{red}|{green}|{blue}", "fadeIn": 0}]
    return f"#{json.dumps(frames, separators=(',', ':'))}"


def decode_rgb(value: Any) -> tuple[int, int, int] | None:
    """Decode a confirmed Poolside RGB light name, returning None for unknown formats."""
    if not isinstance(value, str) or not value.startswith("#["):
        return None
    try:
        frames = json.loads(value[1:])
        rgb_value = frames[0]["RGB"]
        channels = tuple(int(channel) for channel in rgb_value.split("|"))
    except AttributeError, IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError:
        return None
    if len(channels) != _RGB_CHANNEL_COUNT or not all(
        0 <= channel <= _HA_BRIGHTNESS_MAX for channel in channels
    ):
        return None
    red, green, blue = channels
    return red, green, blue
