"""The config flow offers only the properties Octopus supplies now."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.octopus_nz.const import (
    CONF_ACCOUNT_NUMBER,
    CONF_PROPERTY_ID,
    DOMAIN,
)

from .conftest import ACCOUNT, BACH, DEAD, HOUSE, account

LOGIN = {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "secret"}


@pytest.fixture(autouse=True)
def no_setup():
    """Creating an entry must not start the real integration."""
    with patch("custom_components.octopus_nz.async_setup_entry", return_value=True):
        yield


def api_returning(acct: dict):
    return patch.multiple(
        "custom_components.octopus_nz.config_flow.OctopusNZApi",
        async_accounts=AsyncMock(return_value=("Me", [ACCOUNT])),
        async_account=AsyncMock(return_value=acct),
    )


async def _start(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    return await hass.config_entries.flow.async_configure(result["flow_id"], LOGIN)


async def test_one_live_property_is_taken_without_asking(hass: HomeAssistant) -> None:
    with api_returning(account(DEAD, HOUSE)):
        result = await _start(hass)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Octopus NZ 2 Home Street"
    assert result["data"] == {**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "5130"}
    assert result["result"].unique_id == f"{ACCOUNT}_5130"


async def test_two_live_properties_are_offered(hass: HomeAssistant) -> None:
    with api_returning(account(DEAD, HOUSE, BACH)):
        result = await _start(hass)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "property"
        options = result["data_schema"].schema[CONF_PROPERTY_ID].config["options"]
        assert [o["value"] for o in options] == ["5130", "7000"]
        assert options[0]["label"] == "2 Home Street, Hometown (OctopusFlexi - Standard User)"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PROPERTY_ID: "7000"}
        )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROPERTY_ID] == "7000"
    assert result["result"].unique_id == f"{ACCOUNT}_7000"


async def test_second_property_can_be_added_beside_the_first(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT}_5130",
        data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "5130"},
    ).add_to_hass(hass)
    with api_returning(account(HOUSE, BACH)):
        result = await _start(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PROPERTY_ID: "7000"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_same_property_twice_is_refused(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        unique_id=f"{ACCOUNT}_5130",
        data={**LOGIN, CONF_ACCOUNT_NUMBER: ACCOUNT, CONF_PROPERTY_ID: "5130"},
    ).add_to_hass(hass)
    with api_returning(account(DEAD, HOUSE)):
        result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_account_without_properties_aborts(hass: HomeAssistant) -> None:
    with api_returning(account()):
        result = await _start(hass)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "no_properties"
