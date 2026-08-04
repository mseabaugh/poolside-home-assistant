"""Conservative Poolside JSON and string-state parsing."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from .exceptions import ProtocolError


def _reject_non_finite(value: str) -> None:
    """Reject non-standard JSON constants."""
    raise ValueError(value)


def parse_state(value: Any) -> Any:
    """Parse string-serialized state without damaging zero-padded identifiers."""
    if not isinstance(value, str):
        return value
    if len(value) > 1 and value.startswith("0") and value.isdigit():
        return value
    try:
        parsed = json.loads(value, parse_constant=_reject_non_finite)
    except json.JSONDecodeError, ValueError:
        return value
    if isinstance(parsed, float) and not math.isfinite(parsed):
        return value
    return parsed


def decode_json_value(value: Any) -> Any:
    """Decode nested JSON strings used by some Poolside RPC responses."""
    current = value
    for _attempt in range(2):
        if not isinstance(current, str):
            break
        try:
            current = json.loads(current, parse_constant=_reject_non_finite)
        except json.JSONDecodeError, ValueError:
            break
    return current


def require_mapping(value: Any, context: str) -> dict[str, Any]:
    """Return a mutable string-key mapping or raise a body-free protocol error."""
    value = decode_json_value(value)
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ProtocolError(f"Expected object for {context}")
    return dict(value)


def unwrap_result(payload: Any) -> Any:
    """Unwrap a JSON-RPC result and surface remote errors as protocol failures."""
    mapping = require_mapping(payload, "JSON-RPC response")
    if "error" in mapping:
        raise ProtocolError("Poolside returned a JSON-RPC error payload")
    if "result" not in mapping:
        raise ProtocolError("Poolside response did not contain a result")
    return decode_json_value(mapping["result"])
