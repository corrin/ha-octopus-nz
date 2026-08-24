"""Import metered consumption and cost as long-term statistics.

Readings arrive about two days late, so they can never be sensor states -- a
sensor records the moment it is written. Statistics are written against the
timestamp the energy was actually used, which is what the Energy dashboard
needs and what makes a year of history possible on first run.

Statistics are hourly, so half-hourly intervals are summed in pairs. New
Zealand's UTC offsets are whole hours, so a UTC hour boundary is also a local
one and no interval ever straddles two buckets.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timedelta

from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STATISTIC_CONSUMPTION, STATISTIC_COST
from .tariff import Tariff

_LOGGER = logging.getLogger(__name__)


async def async_last_sum(hass: HomeAssistant, statistic_id: str) -> tuple[float, datetime | None]:
    """The running total so far, and the hour it belongs to."""
    last = await get_instance(hass).async_add_executor_job(
        get_last_statistics, hass, 1, statistic_id, True, {"sum"}
    )
    if not last or not last.get(statistic_id):
        return 0.0, None
    row = last[statistic_id][0]
    start = row.get("start")
    if isinstance(start, (int, float)):
        start = dt_util.utc_from_timestamp(start)
    return float(row.get("sum") or 0.0), start


def _hourly(rows: list[dict]) -> dict[datetime, float]:
    """Sum interval readings into UTC hour buckets keyed by the hour start."""
    buckets: dict[datetime, float] = defaultdict(float)
    for row in rows:
        stamp = row.get("startAt") or row.get("readAt")
        if not stamp:
            continue
        start = dt_util.parse_datetime(stamp)
        if start is None:
            continue
        hour = dt_util.as_utc(start).replace(minute=0, second=0, microsecond=0)
        buckets[hour] += float(row["value"])
    return dict(buckets)


def _cost_hourly(
    rows: list[dict], tariff: Tariff, timezone
) -> dict[datetime, float]:
    """Cost per UTC hour, pricing each interval by the band it falls in."""
    buckets: dict[datetime, float] = defaultdict(float)
    charged_days: set = set()
    for row in rows:
        stamp = row.get("startAt") or row.get("readAt")
        if not stamp:
            continue
        start = dt_util.parse_datetime(stamp)
        if start is None:
            continue
        local = start.astimezone(timezone)
        rate = tariff.rate_at(local)
        if rate is None:
            continue
        hour = dt_util.as_utc(start).replace(minute=0, second=0, microsecond=0)
        buckets[hour] += float(row["value"]) * rate

        # The fixed daily charge lands once, on the first priced interval of
        # each local day, so a day's total matches the bill.
        if tariff.daily_charge and local.date() not in charged_days:
            charged_days.add(local.date())
            buckets[hour] += tariff.daily_charge
    return dict(buckets)


async def async_import(
    hass: HomeAssistant,
    rows: list[dict],
    tariff: Tariff | None,
    currency: str,
) -> int:
    """Write consumption (and cost, where a tariff is known) statistics.

    Returns the number of hours written.
    """
    if not rows:
        return 0

    timezone = dt_util.get_default_time_zone()
    series: list[tuple[str, str, str, dict[datetime, float]]] = [
        (
            STATISTIC_CONSUMPTION,
            "Octopus NZ Electricity Consumption",
            UnitOfEnergy.KILO_WATT_HOUR,
            _hourly(rows),
        )
    ]
    if tariff and (tariff.has_time_of_use or tariff.flat_rate is not None):
        series.append(
            (
                STATISTIC_COST,
                "Octopus NZ Electricity Cost",
                currency,
                _cost_hourly(rows, tariff, timezone),
            )
        )

    written = 0
    for statistic_id, name, unit, hourly in series:
        if not hourly:
            continue
        running, last_start = await async_last_sum(hass, statistic_id)

        points: list[StatisticData] = []
        for hour in sorted(hourly):
            # Re-importing an hour would double-count it; the recorder keys on
            # start, so skip anything already summed in.
            if last_start is not None and hour <= last_start:
                continue
            running += hourly[hour]
            points.append(
                StatisticData(start=hour, state=hourly[hour], sum=running)
            )

        if not points:
            continue

        async_add_external_statistics(
            hass,
            StatisticMetaData(
                has_mean=False,
                has_sum=True,
                name=name,
                source=DOMAIN,
                statistic_id=statistic_id,
                unit_of_measurement=unit,
            ),
            points,
        )
        written = max(written, len(points))
        _LOGGER.debug("Wrote %d hours to %s", len(points), statistic_id)

    return written
