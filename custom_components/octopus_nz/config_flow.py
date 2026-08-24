"""Config flow for Octopus Energy NZ."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import OctopusNZApi, OctopusNZAuthError, OctopusNZError
from .const import CONF_ACCOUNT_NUMBER, DOMAIN

STEP_USER = vol.Schema(
    {
        vol.Required(CONF_EMAIL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.EMAIL, autocomplete="username")
        ),
        vol.Required(CONF_PASSWORD): TextSelector(
            TextSelectorConfig(
                type=TextSelectorType.PASSWORD, autocomplete="current-password"
            )
        ),
    }
)


class OctopusNZConfigFlow(ConfigFlow, domain=DOMAIN):
    """Sign in, then pick an account if the login has more than one."""

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._accounts: list[str] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            api = OctopusNZApi(
                async_get_clientsession(self.hass),
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                _, accounts = await api.async_accounts()
            except OctopusNZAuthError:
                errors["base"] = "invalid_auth"
            except OctopusNZError:
                errors["base"] = "cannot_connect"
            else:
                self._email = user_input[CONF_EMAIL]
                self._password = user_input[CONF_PASSWORD]
                self._accounts = accounts
                if len(accounts) == 1:
                    return await self._async_create(accounts[0])
                return await self.async_step_account()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return await self._async_create(user_input[CONF_ACCOUNT_NUMBER])

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT_NUMBER): vol.In(self._accounts)}
            ),
        )

    async def _async_create(self, account_number: str) -> ConfigFlowResult:
        await self.async_set_unique_id(account_number)
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Octopus NZ {account_number}",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_ACCOUNT_NUMBER: account_number,
            },
        )

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            api = OctopusNZApi(
                async_get_clientsession(self.hass),
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                await api.async_accounts()
            except OctopusNZAuthError:
                errors["base"] = "invalid_auth"
            except OctopusNZError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PASSWORD): TextSelector(
                        TextSelectorConfig(
                            type=TextSelectorType.PASSWORD,
                            autocomplete="current-password",
                        )
                    )
                }
            ),
            description_placeholders={CONF_EMAIL: entry.data[CONF_EMAIL]},
            errors=errors,
        )
