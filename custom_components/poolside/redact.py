"""Recursive credential and personal-information redaction."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from typing import Any, Final

REDACTED: Final = "<REDACTED>"

_BEARER = re.compile(r"(?i)\bBearer\s+[^\s,;]+")
_EMAIL = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_IPV4 = re.compile(
    r"(?<!\d)(?:25[0-5]|2[0-4]\d|1?\d?\d)"
    r"(?:\.(?:25[0-5]|2[0-4]\d|1?\d?\d)){3}(?!\d)"
)
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_UUID = re.compile(
    r"(?i)\b[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}\b"
)

_SENSITIVE_KEYS = frozenset(
    {
        "accesstoken",
        "address",
        "authorization",
        "bearer",
        "city",
        "connectionid",
        "connectionuuid",
        "deviceid",
        "deviceuuid",
        "email",
        "firstname",
        "installationid",
        "ip",
        "lastip",
        "lastname",
        "lat",
        "latitude",
        "location",
        "lon",
        "longitude",
        "password",
        "postalcode",
        "secret",
        "serial",
        "serialnumber",
        "siteid",
        "siteuuid",
        "street",
        "token",
        "traceid",
        "userid",
        "useruuid",
        "vpnaddress",
        "vpnpublickey",
        "zip",
        "zipcode",
    }
)


def _normalized_key(key: object) -> str:
    """Normalize a mapping key for the sensitive-key denylist."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def redact_text(value: str) -> str:
    """Redact recognizable credentials and identifiers from text."""
    value = _BEARER.sub("Bearer <REDACTED>", value)
    value = _EMAIL.sub(REDACTED, value)
    value = _JWT.sub(REDACTED, value)
    value = _UUID.sub(REDACTED, value)
    return _IPV4.sub(REDACTED, value)


def redact(value: Any) -> Any:
    """Return a recursively redacted copy of JSON-compatible data."""
    if isinstance(value, Mapping):
        return {
            key: REDACTED if _normalized_key(key) in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact(item) for item in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


def fingerprint(*values: str) -> str:
    """Create a stable non-reversible identifier for config-entry deduplication."""
    canonical = "\x00".join(sorted(values)).encode()
    return hashlib.sha256(canonical).hexdigest()
