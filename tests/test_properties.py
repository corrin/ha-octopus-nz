"""Which property is live, which plan applies, and what a property is called."""

from custom_components.octopus_nz.properties import (
    is_live,
    live_properties,
    property_label,
)
from custom_components.octopus_nz.tariff import parse_tariff, pick_agreement

from .conftest import BACH, DEAD, HOUSE, prop


def test_live_is_having_an_active_agreement() -> None:
    assert is_live(HOUSE)
    assert not is_live(DEAD)


def test_live_properties_drops_ended_supply() -> None:
    assert live_properties([DEAD, HOUSE]) == [HOUSE]
    assert live_properties([DEAD, HOUSE, BACH]) == [HOUSE, BACH]


def test_live_properties_falls_back_to_all_when_none_is_live() -> None:
    other = prop("1", "x", live=False)
    assert live_properties([DEAD, other]) == [DEAD, other]


def test_plan_is_per_property() -> None:
    house = parse_tariff(pick_agreement(HOUSE))
    bach = parse_tariff(pick_agreement(BACH))
    assert house.unit_rates["PEAK"] == 0.38
    assert bach.unit_rates["PEAK"] == 0.30


def test_ended_property_uses_its_latest_agreement() -> None:
    assert pick_agreement(DEAD)["validFrom"] == "2026-04-01"


def test_label_prefers_label_then_first_address_line() -> None:
    assert property_label(HOUSE) == "2 Home Street"
    assert property_label({**HOUSE, "label": "Home"}) == "Home"
    assert property_label({"id": "9", "address": None}) == "Property 9"
