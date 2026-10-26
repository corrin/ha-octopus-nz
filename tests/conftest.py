"""Shared fixtures: a fake Kraken account with properties in different states."""

from __future__ import annotations

from typing import Any

import pytest

ACCOUNT = "A-1234ABCD"


def plan(agreement_id: str, valid_from: str, peak: float = 38.0) -> dict[str, Any]:
    """An agreement node as the account query returns it."""
    return {
        "id": agreement_id,
        "displayName": "OctopusFlexi - Standard User",
        "validFrom": valid_from,
        "rates": [
            {"displayLabel": "Peak", "touBucketName": "PEAK", "unitType": "kWh",
             "rateIncludingTax": peak, "rateExcludingTax": peak / 1.15},
            {"displayLabel": "Peak Export", "touBucketName": "PEAK", "unitType": "kWh",
             "rateIncludingTax": -19.0, "rateExcludingTax": -19.0},
            {"displayLabel": "Daily", "touBucketName": None, "unitType": "Days on supply",
             "rateIncludingTax": 375.0, "rateExcludingTax": 326.0},
        ],
        "timeOfUseScheme": [
            {"name": "PEAK", "times": [{"dayOfWeek": d, "start": "00:00:00", "end": "23:59:59"}
                                       for d in range(1, 8)]},
        ],
    }


def prop(prop_id: str, address: str, live: bool, peak: float = 38.0) -> dict[str, Any]:
    """A property with one meter point; live means it has an active agreement."""
    current = plan(f"{prop_id}-a", "2026-04-01", peak)
    return {
        "id": prop_id,
        "address": address,
        "label": None,
        "meterPoints": [
            {
                "id": f"{prop_id}-m",
                "activeAgreement": current if live else None,
                "agreements": [current, plan(f"{prop_id}-old", "2024-01-01", peak)],
            }
        ],
    }


def account(*properties: dict[str, Any]) -> dict[str, Any]:
    return {"number": ACCOUNT, "status": "ACTIVE", "balance": 0, "properties": list(properties)}


DEAD = prop("12306", "1 Old Road, Oldtown", live=False, peak=34.0)
HOUSE = prop("5130", "2 Home Street, Hometown", live=True)
BACH = prop("7000", "3 Beach Road, Beachtown", live=True, peak=30.0)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """Load custom_components/octopus_nz, with the recorder it depends on, in every test."""
    return
