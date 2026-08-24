"""Time-of-use windows and unit rates.

Kraken exposes the plan's rates on account.agreements[].rates and the windows
they apply in on account.agreements[].timeOfUseScheme. agreementRates() looks
like the natural query for this but returns KT-CT-1111 for a customer login.

Rates arrive in cents per kWh; the daily charge arrives in cents per day.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from .const import BUCKET_SLUGS

# Kraken's dayOfWeek is ISO: 1 = Monday .. 7 = Sunday.
_UNIT_DAILY = "Days on supply"


@dataclass(frozen=True)
class Window:
    """One time-of-use window on one weekday."""

    bucket: str
    iso_weekday: int
    start: time
    end: time

    def covers(self, moment: datetime) -> bool:
        return (
            moment.isoweekday() == self.iso_weekday
            and self.start <= moment.time() < self.end
        )


@dataclass
class Tariff:
    """The plan's rates and the windows they apply in."""

    name: str = ""
    windows: list[Window] = field(default_factory=list)
    unit_rates: dict[str, float] = field(default_factory=dict)  # bucket -> $/kWh
    flat_rate: float | None = None  # $/kWh when the plan has no TOU bands
    daily_charge: float | None = None  # $/day

    @property
    def has_time_of_use(self) -> bool:
        return bool(self.windows and self.unit_rates)

    def bucket_at(self, moment: datetime) -> str | None:
        """Which time-of-use band `moment` (in the account's timezone) falls in."""
        for window in self.windows:
            if window.covers(moment):
                return window.bucket
        return None

    def slug_at(self, moment: datetime) -> str | None:
        bucket = self.bucket_at(moment)
        return BUCKET_SLUGS.get(bucket, bucket) if bucket else None

    def rate_at(self, moment: datetime) -> float | None:
        """Unit rate in dollars per kWh applying at `moment`."""
        if not self.has_time_of_use:
            return self.flat_rate
        bucket = self.bucket_at(moment)
        return self.unit_rates.get(bucket) if bucket else None


def _parse_time(raw: str) -> time:
    return time.fromisoformat(raw)


def parse_tariff(agreement: dict[str, Any]) -> Tariff:
    """Build a Tariff from one account.agreements[] node."""
    tariff = Tariff(name=agreement.get("displayName") or "")

    for band in agreement.get("timeOfUseScheme") or []:
        bucket = band.get("name")
        for slot in band.get("times") or []:
            tariff.windows.append(
                Window(
                    bucket=bucket,
                    iso_weekday=int(slot["dayOfWeek"]),
                    start=_parse_time(slot["start"]),
                    end=_parse_time(slot["end"]),
                )
            )

    for rate in agreement.get("rates") or []:
        price = rate.get("rateIncludingTax")
        if price is None:
            continue
        dollars = float(price) / 100.0
        if rate.get("unitType") == _UNIT_DAILY:
            tariff.daily_charge = dollars
        elif bucket := rate.get("touBucketName"):
            tariff.unit_rates[bucket] = dollars
        else:
            tariff.flat_rate = dollars

    return tariff


def pick_agreement(account: dict[str, Any]) -> dict[str, Any] | None:
    """The agreement in force -- the latest by validFrom."""
    agreements = account.get("agreements") or []
    if not agreements:
        return None
    return max(agreements, key=lambda a: a.get("validFrom") or "")
