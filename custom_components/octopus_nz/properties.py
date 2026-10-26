"""Which of an account's properties to read, and what to call it.

An account keeps every property it has been supplied at. Kraken lists a
property whose supply has ended alongside the current one, in no useful order,
and occupancyPeriods does not help: it leaves effectiveTo open on both. What
does tell them apart is the meter point's activeAgreement, which is null once
supply ends.
"""

from __future__ import annotations

from typing import Any


def is_live(prop: dict[str, Any]) -> bool:
    """Whether Octopus currently supplies this property."""
    return any(meter.get("activeAgreement") for meter in prop.get("meterPoints") or [])


def live_properties(properties: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The properties being supplied now, or all of them if none is.

    A new customer can have a property before its agreement starts; showing
    everything then is better than showing nothing.
    """
    return [p for p in properties if is_live(p)] or list(properties)


def property_label(prop: dict[str, Any]) -> str:
    """A short name: the customer's label, else the first line of the address."""
    if prop.get("label"):
        return prop["label"]
    address = (prop.get("address") or "").strip()
    first = address.replace("\n", ",").split(",")[0].strip()
    return first or f"Property {prop['id']}"
