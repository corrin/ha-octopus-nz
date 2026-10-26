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
    CONF_LEGACY_IDS,
    CONF_PROPERTY_ID,
    CONSUMPTION,
    DAY_INTERVAL,
    DOMAIN,
    GENERATION,
    INITIAL_BACKFILL_DAYS,
    STATISTIC_CONSUMPTION,
    STATISTIC_EXPORT,
    SUMMARY_DAYS,
    THIRTY_MIN_INTERVAL,
    UPDATE_INTERVAL,
)
from .properties import is_live, live_properties, property_label
from .statistics import async_import, async_import_export, async_last_sum
from .tariff import Tariff, parse_tariff, pick_agreement

_LOGGER = logging.getLogger(__name__)

# Kraken rejects windows longer than this in one request.
_MAX_WINDOW = timedelta(days=90)


@dataclass
class OctopusNZData:
    """What the sensors read."""

    account_number: str
    property_id: str | None = None
    status: str | None = None
    balance: float | None = None
    address: str | None = None
    tariff: Tariff | None = None
    latest_interval: float | None = None
    latest_interval_start: datetime | None = None
    last_full_day: float | None = None
    last_full_day_date: Any = None
    latest_interval_export: float | None = None
    latest_interval_export_start: datetime | None = None
    last_full_day_export: float | None = None
    last_full_day_export_date: Any = None
    hours_written: int = 0


class OctopusNZCoordinator(DataUpdateCoordinator[OctopusNZData]):
    """Fetches meter data and writes it into long-term statistics."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: OctopusNZApi,
        account_number: str,
        property_id: str | None,
        legacy_ids: bool,
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
        # None only for an entry made before per-property entries, until the
        # first sync pins it to its live property.
        self.property_id = property_id
        self.legacy_ids = legacy_ids
        self.property_label: str | None = None

    @property
    def key(self) -> str:
        """Prefix for this entry's device and entity unique ids."""
        if self.legacy_ids:
            return self.account_number
        return f"{self.account_number}_{self.property_id}"

    @property
    def _statistic_suffix(self) -> str:
        return "" if self.legacy_ids else f"_{self.property_id}"

    def _find_property(self, properties: list[dict]) -> dict:
        """This entry's property, pinning a pre-per-property entry on first sight."""
        if self.property_id is not None:
            for prop in properties:
                if prop["id"] == self.property_id:
                    return prop
            raise UpdateFailed(
                f"Property {self.property_id} is no longer on account {self.account_number}"
            )

        # An entry from before per-property entries read properties[0], which
        # can be a property whose supply has ended. Read the first live one
        # instead, and pin it once it is known to be live so a second live
        # property can never take its place.
        prop = live_properties(properties)[0]
        if is_live(prop):
            self.property_id = prop["id"]
            entry = self.config_entry
            unique_id = f"{self.account_number}_{prop['id']}"
            taken = any(
                other.unique_id == unique_id
                for other in self.hass.config_entries.async_entries(DOMAIN)
                if other.entry_id != entry.entry_id
            )
            self.hass.config_entries.async_update_entry(
                entry,
                data={**entry.data, CONF_PROPERTY_ID: prop["id"], CONF_LEGACY_IDS: True},
                unique_id=entry.unique_id if taken else unique_id,
            )
            _LOGGER.info(
                "Account %s: reading property %s (%s), the one Octopus supplies now",
                self.account_number,
                prop["id"],
                property_label(prop),
            )
        return prop

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
        prop = self._find_property(properties)
        self._property_id = prop["id"]
        self.property_label = property_label(prop)

        agreement = pick_agreement(prop)
        tariff = parse_tariff(agreement) if agreement else None

        data = OctopusNZData(
            account_number=self.account_number,
            property_id=prop["id"],
            status=account.get("status"),
            # Kraken holds balances in cents.
            balance=(account["balance"] / 100.0 if account.get("balance") is not None else None),
            address=prop.get("address"),
            tariff=tariff,
        )

        currency = self.hass.config.currency or "NZD"
        suffix = self._statistic_suffix
        label = None if self.legacy_ids else self.property_label
        try:
            rows = await self._async_fetch_new(f"{STATISTIC_CONSUMPTION}{suffix}", CONSUMPTION)
            if rows:
                data.hours_written = await async_import(
                    self.hass, rows, tariff, currency, suffix, label
                )

            # Export only exists once Octopus has attached export rates to the
            # plan, so a house without solar never accrues an empty statistic.
            if tariff and tariff.has_export:
                rows = await self._async_fetch_new(f"{STATISTIC_EXPORT}{suffix}", GENERATION)
                if rows:
                    await async_import_export(self.hass, rows, tariff, currency, suffix, label)

            await self._async_summarise(data, CONSUMPTION)
            if tariff and tariff.has_export:
                await self._async_summarise(data, GENERATION)
        except OctopusNZError as err:
            raise UpdateFailed(str(err)) from err
        return data

    async def _async_summarise(self, data: OctopusNZData, direction: str) -> None:
        """Fill in the headline figures on their own fixed window.

        These cannot be read off the statistics fetch: once the backfill is
        done that window is only a couple of hours wide and never contains a
        whole day, which would leave the daily sensor unknown for ever.
        """
        now = dt_util.utcnow()
        export = direction == GENERATION

        days = await self.api.async_measurements(
            self._property_id, now - timedelta(days=SUMMARY_DAYS), now, DAY_INTERVAL, direction
        )
        # A day Octopus has only partly received comes back short, so duration
        # is what distinguishes a complete day from one still filling up.
        complete = [d for d in days if d.get("durationInSeconds") == 86400]
        if complete:
            newest = max(complete, key=lambda d: d["startAt"])
            value = float(newest["value"])
            date = (
                dt_util.parse_datetime(newest["startAt"])
                .astimezone(dt_util.get_default_time_zone())
                .date()
            )
            if export:
                data.last_full_day_export, data.last_full_day_export_date = value, date
            else:
                data.last_full_day, data.last_full_day_date = value, date

        recent = await self.api.async_measurements(
            self._property_id, now - timedelta(days=3), now, THIRTY_MIN_INTERVAL, direction
        )
        if recent:
            newest = max(recent, key=lambda r: r["startAt"])
            value = float(newest["value"])
            start = dt_util.parse_datetime(newest["startAt"])
            if export:
                data.latest_interval_export, data.latest_interval_export_start = value, start
            else:
                data.latest_interval, data.latest_interval_start = value, start

    async def _async_fetch_new(self, statistic_id: str, direction: str) -> list[dict]:
        """Everything metered since the last statistic, backfilling on first run."""
        _, last_start = await async_last_sum(self.hass, statistic_id)
        now = dt_util.utcnow()
        if last_start is None:
            start = now - timedelta(days=INITIAL_BACKFILL_DAYS)
            _LOGGER.info(
                "No existing %s statistics; backfilling %d days for %s",
                direction.lower(),
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
                await self.api.async_measurements(
                    self._property_id, window_start, window_end, THIRTY_MIN_INTERVAL, direction
                )
            )
            window_start = window_end
        return rows
