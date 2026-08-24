"""Diagnostics for Octopus Energy NZ."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import OctopusNZConfigEntry

REDACT = {CONF_EMAIL, CONF_PASSWORD, "address", "account_number"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OctopusNZConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = entry.runtime_data
    data = coordinator.data
    tariff = data.tariff if data else None

    return {
        "entry": async_redact_data(dict(entry.data), REDACT),
        "data": async_redact_data(
            {
                "status": data.status if data else None,
                "balance": data.balance if data else None,
                "address": data.address if data else None,
                "account_number": data.account_number if data else None,
                "latest_interval": data.latest_interval if data else None,
                "latest_interval_start": (
                    data.latest_interval_start.isoformat()
                    if data and data.latest_interval_start
                    else None
                ),
                "last_full_day": data.last_full_day if data else None,
                "hours_written": data.hours_written if data else None,
            },
            REDACT,
        ),
        "tariff": (
            {
                "name": tariff.name,
                "unit_rates": tariff.unit_rates,
                "flat_rate": tariff.flat_rate,
                "daily_charge": tariff.daily_charge,
                "windows": [
                    {
                        "bucket": w.bucket,
                        "iso_weekday": w.iso_weekday,
                        "start": w.start.isoformat(),
                        "end": w.end.isoformat(),
                    }
                    for w in tariff.windows
                ],
            }
            if tariff
            else None
        ),
    }
