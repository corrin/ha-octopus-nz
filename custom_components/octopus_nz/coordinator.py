"""Poll Kraken and keep statistics up to date."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import OctopusNZApi, OctopusNZAuthError, OctopusNZError
from .const import (
    DOMAIN,
    INITIAL_BACKFILL_DAYS,
    STATISTIC_CONSUMPTION,
    UPDATE_INTERVAL,
)
from .statistics import async_import, async_last_sum
from .tariff import Tariff, parse_tariff, pick_agreement

_LOGGER = logging.getLogger(__name__)

# Kraken rejects windows longer than this in one request.
_MAX_WINDOW = timedelta(days=90)


@dataclass
class OctopusNZData:
    """What the sensors read."""

    account_number: str
    status: str | None = None
    balance: float | None = None
    address: str | None = None
    tariff: Tariff | None = None
    latest_interval: float | None = None
    latest_interval_start: datetime | None = None
    last_full_day: float | None = None
    last_full_day_date: Any = None
    hours_written: int = 0


class OctopusNZCoordinator(DataUpdateCoordinator[OctopusNZData]):
    """Fetches meter data and writes it into long-term statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: OctopusNZApi,
        account_number: str,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN} {account_number}",
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.api = api
        self.account_number = account_number
        self._property_id: str | None = None

    async def _async_update_data(self) -> OctopusNZData:
        try:
            account = await self.api.async_account(self.account_number)
        except OctopusNZAuthError as err:
            raise UpdateFailed(f"Octopus NZ rejected the credentials: {err}") from err
        except OctopusNZError as err:
            raise UpdateFailed(str(err)) from err

        properties = account.get("properties") or []
        if not properties:
            raise UpdateFailed("Account has no properties")
        self._property_id = properties[0]["id"]

        agreement = pick_agreement(account)
        tariff = parse_tariff(agreement) if agreement else None

        data = OctopusNZData(
            account_number=self.account_number,
            status=account.get("status"),
            # Kraken holds balances in cents.
            balance=(account["balance"] / 100.0 if account.get("balance") is not None else None),
            address=properties[0].get("address"),
            tariff=tariff,
        )

        try:
            rows = await self._async_fetch_new()
        except OctopusNZError as err:
            raise UpdateFailed(str(err)) from err

        if rows:
            currency = self.hass.config.currency or "NZD"
            data.hours_written = await async_import(self.hass, rows, tariff, currency)
            self._summarise(rows, data)

        return data

    async def _async_fetch_new(self) -> list[dict]:
        """Everything metered since the last statistic, backfilling on first run."""
        _, last_start = await async_last_sum(self.hass, STATISTIC_CONSUMPTION)
        now = dt_util.utcnow()
        if last_start is None:
            start = now - timedelta(days=INITIAL_BACKFILL_DAYS)
            _LOGGER.info(
                "No existing statistics; backfilling %d days for %s",
                INITIAL_BACKFILL_DAYS,
                self.account_number,
            )
        else:
            # Re-read the last hour so a partially reported hour is corrected.
            start = last_start

        rows: list[dict] = []
        window_start = start
        while window_start < now:
            window_end = min(window_start + _MAX_WINDOW, now)
            rows.extend(
                await self.api.async_measurements(self._property_id, window_start, window_end)
            )
            window_start = window_end
        return rows

    @staticmethod
    def _summarise(rows: list[dict], data: OctopusNZData) -> None:
        """Fill in the headline figures the sensors show."""
        timezone = dt_util.get_default_time_zone()
        dated = []
        for row in rows:
            stamp = row.get("startAt") or row.get("readAt")
            start = dt_util.parse_datetime(stamp) if stamp else None
            if start is not None:
                dated.append((start, float(row["value"])))
        if not dated:
            return
        dated.sort()

        data.latest_interval_start, data.latest_interval = dated[-1]

        # The most recent day with a full set of intervals. Today and often
        # yesterday are still incomplete, so the last complete day is the
        # newest figure that can be trusted.
        by_day: dict[Any, list[float]] = {}
        for start, value in dated:
            by_day.setdefault(start.astimezone(timezone).date(), []).append(value)
        for day in sorted(by_day, reverse=True):
            if len(by_day[day]) >= 48:
                data.last_full_day = sum(by_day[day])
                data.last_full_day_date = day
                break
