"""Entries read their own property; entries from before per-property setup keep their ids."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octopus_nz.const import (
    CONF_ACCOUNT_NUMBER,
    CONF_LEGACY_IDS,
    CONF_PROPERTY_ID,
    DOMAIN,
)

from .conftest import ACCOUNT, BACH, DEAD, HOUSE, account

LOGIN = {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret"}
READING = {"value": "1.5", "startAt": "2026-10-20T00:00:00+00:00", "durationInSeconds": 1800}


async def _setup(hass: HomeAssistant, entry: MockConfigEntry, acct: dict):
    """Set the entry up against a fake Kraken; return the statistics calls made."""
    entry.add_to_hass(hass)
    imported = AsyncMock(return_value=1)
    exported = AsyncMock(return_value=1)
    measurements = AsyncMock(return_value=[READING])
    with (
        patch.multiple(
            "custom_components.octopus_nz.OctopusNZApi",
            async_token=AsyncMock(return_value="t"),
            async_account=AsyncMock(return_value=acct),
            async_measurements=measurements,
        ),
        patch("custom_components.octopus_nz.coordinator.async_last_sum",
              AsyncMock(return_value=(0.0, None))),
        patch("custom_components.octopus_nz.coordinator.async_import", imported),
        patch("custom_components.octopus_nz.coordinator.async_import_export", exported),
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return imported, exported, measurements


async def test_old_entry_pins_the_live_property_and_keeps_its_ids(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN, unique_id=ACCOUNT, data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT}
    )
    imported, exported, measurements = await _setup(hass, entry, account(DEAD, HOUSE))

    assert entry.state is ConfigEntryState.LOADED
    assert entry.data[CONF_PROPERTY_ID] == "5130"
    assert entry.data[CONF_LEGACY_IDS] is True
    assert entry.unique_id == f"{ACCOUNT}_5130"
    # Readings come from the live property, never the one whose supply ended.
    assert {c.args[0] for c in measurements.call_args_list} == {"5130"}
    # Statistics keep their original ids and names (no suffix, no label).
    assert imported.call_args.args[4:] == ("", None)
    assert exported.call_args.args[4:] == ("", None)
    # Entity unique ids are unchanged, so entity ids and history carry on.
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert f"{ACCOUNT}_last_full_day" in unique_ids


async def test_pinned_old_entry_stays_put_when_a_second_property_goes_live(
    hass: HomeAssistant,
) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT}_5130",
        data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "5130", CONF_LEGACY_IDS: True},
    )
    _, _, measurements = await _setup(hass, entry, account(BACH, HOUSE))
    assert entry.state is ConfigEntryState.LOADED
    assert {c.args[0] for c in measurements.call_args_list} == {"5130"}


async def test_new_entry_has_its_own_ids_and_plan(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT}_7000",
        data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "7000"},
    )
    imported, _, measurements = await _setup(hass, entry, account(HOUSE, BACH))

    assert entry.state is ConfigEntryState.LOADED
    assert {c.args[0] for c in measurements.call_args_list} == {"7000"}
    assert imported.call_args.args[4:] == ("_7000", "3 Beach Road")
    tariff = imported.call_args.args[2]
    assert tariff.unit_rates["PEAK"] == 0.30
    unique_ids = {e.unique_id for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)}
    assert f"{ACCOUNT}_7000_last_full_day" in unique_ids


async def test_property_removed_from_account_fails_the_sync(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT}_7000",
        data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "7000"},
    )
    # Everything else is mocked to succeed, so only the missing property can fail it.
    _, _, measurements = await _setup(hass, entry, account(HOUSE))
    assert entry.state is ConfigEntryState.SETUP_RETRY
    measurements.assert_not_called()
