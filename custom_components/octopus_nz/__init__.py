"""The Octopus Energy NZ integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import OctopusNZApi, OctopusNZAuthError, OctopusNZError
from .const import CONF_ACCOUNT_NUMBER
from .coordinator import OctopusNZCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type OctopusNZConfigEntry = ConfigEntry[OctopusNZCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: OctopusNZConfigEntry) -> bool:
    """Set up Octopus Energy NZ from a config entry."""
    api = OctopusNZApi(
        async_get_clientsession(hass),
        entry.data[CONF_EMAIL],
        entry.data[CONF_PASSWORD],
    )

    try:
        await api.async_token()
    except OctopusNZAuthError as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except OctopusNZError as err:
        raise ConfigEntryNotReady(str(err)) from err

    coordinator = OctopusNZCoordinator(
        hass, entry, api, entry.data[CONF_ACCOUNT_NUMBER]
    )
    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OctopusNZConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
