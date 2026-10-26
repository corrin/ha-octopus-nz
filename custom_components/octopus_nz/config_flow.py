"""Config flow for Octopus Energy NZ."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import OctopusNZApi, OctopusNZAuthError, OctopusNZError
from .const import CONF_ACCOUNT_NUMBER, CONF_PROPERTY_ID, DOMAIN
from .properties import is_live, live_properties, property_label
from .tariff import pick_agreement

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
    """Sign in, then pick an account and a property where there is a choice.

    Each entry reads one property. An account with two properties supplied at
    once (a house and a bach, say) is added twice, once for each.
    """

    VERSION = 1

    def __init__(self) -> None:
        self._email: str = ""
        self._password: str = ""
        self._api: OctopusNZApi | None = None
        self._accounts: list[str] = []
        self._account: str = ""
        self._properties: dict[str, dict[str, Any]] = {}

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
                self._api = api
                self._accounts = accounts
                if len(accounts) == 1:
                    self._account = accounts[0]
                    return await self.async_step_property()
                return await self.async_step_account()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER, errors=errors
        )

    async def async_step_account(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._account = user_input[CONF_ACCOUNT_NUMBER]
            return await self.async_step_property()

        return self.async_show_form(
            step_id="account",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT_NUMBER): vol.In(self._accounts)}
            ),
        )

    async def async_step_property(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the property, offering only those Octopus supplies now.

        An account keeps properties the customer has left; those are not
        offered while a live one exists. One candidate is taken without asking.
        """
        if user_input is not None:
            return await self._async_create(self._properties[user_input[CONF_PROPERTY_ID]])

        if not self._properties:
            assert self._api is not None
            try:
                account = await self._api.async_account(self._account)
            except OctopusNZError:
                return self.async_abort(reason="cannot_connect")
            candidates = live_properties(account.get("properties") or [])
            if not candidates:
                return self.async_abort(reason="no_properties")
            self._properties = {p["id"]: p for p in candidates}

        if len(self._properties) == 1:
            return await self._async_create(next(iter(self._properties.values())))

        options = [
            SelectOptionDict(value=prop_id, label=_describe(prop))
            for prop_id, prop in self._properties.items()
        ]
        return self.async_show_form(
            step_id="property",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROPERTY_ID): SelectSelector(
                        SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                    )
                }
            ),
            description_placeholders={"account": self._account},
        )

    async def _async_create(self, prop: dict[str, Any]) -> ConfigFlowResult:
        await self.async_set_unique_id(f"{self._account}_{prop['id']}")
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=f"Octopus NZ {property_label(prop)}",
            data={
                CONF_EMAIL: self._email,
                CONF_PASSWORD: self._password,
                CONF_ACCOUNT_NUMBER: self._account,
                CONF_PROPERTY_ID: prop["id"],
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


def _describe(prop: dict[str, Any]) -> str:
    """Picker text: the address and the plan it is on."""
    agreement = pick_agreement(prop)
    plan = agreement.get("displayName") if agreement else None
    where = prop.get("address") or property_label(prop)
    if not is_live(prop):
        return f"{where} (no current plan)"
    return f"{where} ({plan})" if plan else where
