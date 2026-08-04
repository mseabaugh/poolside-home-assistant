"""Privacy-preserving diagnostics for Poolside config entries."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import PoolsideConfigEntry
from .redact import REDACTED, fingerprint, redact


async def async_get_config_entry_diagnostics(
    _hass: HomeAssistant, entry: PoolsideConfigEntry
) -> dict[str, Any]:
    """Return useful counts and classifications without remote identifiers or payloads."""
    coordinator = entry.runtime_data.coordinator
    sites = [
        {
            "alerts": len(site.alerts),
            "combined_controls": len(site.combined_controls),
            "controls": len(site.controls),
            "equipment": len(site.equipment),
            "fingerprint": fingerprint(site.uuid)[:12],
            "name": REDACTED,
            "schedule_present": bool(site.schedule_document),
            "themes": len(site.themes),
        }
        for site in coordinator.data.sites.values()
    ]
    return {
        "config_entry": redact(dict(entry.data)),
        "last_update_success": coordinator.last_update_success,
        "site_count": len(sites),
        "sites": sorted(sites, key=lambda site: site["fingerprint"]),
    }
