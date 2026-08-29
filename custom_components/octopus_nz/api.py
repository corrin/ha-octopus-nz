"""Async client for Octopus Energy NZ's Kraken GraphQL API.

Kraken issues a customer nothing durable: viewer.liveSecretKey is null on the NZ
tenant, obtainLongLivedRefreshToken is reserved for third-party organisations,
and refresh tokens last a week. Long-running unattended use therefore keeps the
password and re-authenticates when the refresh token runs out.

obtainKrakenToken accepts email and password even though introspection hides
both fields -- ObtainJSONWebTokenInput advertises only APIKey,
organizationSecretKey, preSignedKey and refreshToken. Sending them returns a
credential error (KT-CT-1138) rather than an unknown-field error.

Data freshness is bounded by the tenant, not by the query. Readings stop at the
most recent local midnight and a new whole day lands around 21:00 NZ; the newest
half hour is therefore 21-45 hours old depending on when you ask. Everything
that could plausibly beat that has been tried and cannot:

  - property.measurements at RAW_INTERVAL -- "readings as provided", i.e. before
    aggregation -- stops at the identical boundary, so the gap is upstream of
    Kraken rather than an artefact of bucketing. HOUR_INTERVAL and DAY_INTERVAL
    likewise; FIVE_MIN_INTERVAL and FIFTEEN_MIN_INTERVAL raise KT-CT-4710.
  - readingQuality: ESTIMATE returns zero rows, so nothing is being estimated
    forward into the gap for this ICP.
  - Query.estimatedSupplyPointReadings does extrapolate past the actuals, but a
    customer viewer gets KT-CT-1111 (permission denied). It is an ops field.
  - supplyPoint.readings raises KT-CT-4721 for every ReadingTypes value on
    NZL_ELECTRICITY. Present in the schema, unimplemented in this market.
  - smartMeterTelemetry, which carries near-live consumption on the UK tenant,
    does not exist in the NZ schema at all.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from aiohttp import ClientError, ClientSession

from .const import API_URL, CONSUMPTION, THIRTY_MIN_INTERVAL

_LOGGER = logging.getLogger(__name__)


class OctopusNZError(Exception):
    """A Kraken request failed."""


class OctopusNZAuthError(OctopusNZError):
    """Credentials were rejected."""


_OBTAIN = """
mutation($i: ObtainJSONWebTokenInput!) {
  obtainKrakenToken(input: $i) { token refreshToken refreshExpiresIn }
}"""

_VIEWER = """
query { viewer { fullName accounts { number } } }"""

_ACCOUNT = """
query($n: String!) {
  account(accountNumber: $n) {
    number
    status
    balance
    properties { id address }
    agreements {
      id
      displayName
      validFrom
      rates {
        displayLabel
        touBucketName
        unitType
        rateIncludingTax
        rateExcludingTax
      }
      timeOfUseScheme { name times { dayOfWeek start end } }
    }
  }
  supplyPoints(accountNumber: $n, first: 10) {
    edges { node { id marketName externalIdentifier } }
  }
}"""

# property.measurements is the only reading path that works on this tenant.
# supplyPoint.readings(readingType: INTERVAL) returns KT-CT-4721 "Cannot query
# for the specified reading type" for every reading type in NZL_ELECTRICITY.
_MEASUREMENTS = """
query($pid: ID!, $s: DateTime!, $e: DateTime!, $f: [UtilityFiltersInput], $after: String) {
  property(id: $pid) {
    measurements(startAt: $s, endAt: $e, utilityFilters: $f, first: 500, after: $after) {
      totalCount
      pageInfo { hasNextPage endCursor }
      edges {
        node {
          value
          unit
          readAt
          ... on IntervalMeasurementType { startAt endAt durationInSeconds }
        }
      }
    }
  }
}"""


class OctopusNZApi:
    """Talks to Kraken, holding a token across calls."""

    def __init__(self, session: ClientSession, email: str, password: str) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._token: str | None = None
        self._token_expires: datetime | None = None
        self._refresh_token: str | None = None
        self._refresh_expires: datetime | None = None

    # -- transport ---------------------------------------------------------
    async def _post(
        self, query: str, variables: dict[str, Any] | None = None, token: str | None = None
    ) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = token
        try:
            async with self._session.post(
                API_URL,
                json={"query": query, "variables": variables or {}},
                headers=headers,
            ) as resp:
                payload = await resp.json()
        except ClientError as err:
            raise OctopusNZError(f"Cannot reach Kraken: {err}") from err

        if errors := payload.get("errors"):
            first = errors[0]
            ext = first.get("extensions", {})
            code = ext.get("errorCode", "")
            message = ext.get("errorDescription") or first.get("message")
            if code in ("KT-CT-1138", "KT-CT-1139", "KT-CT-1135"):
                raise OctopusNZAuthError(message)
            raise OctopusNZError(f"{code} {message}".strip())
        return payload["data"]

    # -- auth --------------------------------------------------------------
    def _remember(self, got: dict[str, Any]) -> str:
        self._token = got["token"]
        # Access tokens last an hour; renew early so a slow call cannot straddle
        # the boundary.
        self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=55)
        if got.get("refreshToken"):
            self._refresh_token = got["refreshToken"]
        if raw := got.get("refreshExpiresIn"):
            # Kraken returns an absolute unix timestamp despite the "In" name.
            self._refresh_expires = (
                datetime.fromtimestamp(raw, timezone.utc)
                if raw > 1_000_000_000
                else datetime.now(timezone.utc) + timedelta(seconds=raw)
            )
        return self._token

    async def async_token(self) -> str:
        """A live access token, renewing or re-authenticating as needed."""
        now = datetime.now(timezone.utc)
        if self._token and self._token_expires and now < self._token_expires:
            return self._token

        if self._refresh_token and self._refresh_expires and now < self._refresh_expires:
            try:
                data = await self._post(_OBTAIN, {"i": {"refreshToken": self._refresh_token}})
                return self._remember(data["obtainKrakenToken"])
            except OctopusNZError:
                _LOGGER.debug("Refresh token rejected, falling back to password")

        data = await self._post(
            _OBTAIN, {"i": {"email": self._email, "password": self._password}}
        )
        return self._remember(data["obtainKrakenToken"])

    async def async_query(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return await self._post(query, variables, token=await self.async_token())

    # -- calls -------------------------------------------------------------
    async def async_accounts(self) -> tuple[str, list[str]]:
        """The viewer's name and account numbers."""
        viewer = (await self.async_query(_VIEWER, {}))["viewer"]
        accounts = [a["number"] for a in (viewer.get("accounts") or [])]
        if not accounts:
            raise OctopusNZError("This login has no accounts")
        return viewer.get("fullName") or "", accounts

    async def async_account(self, account_number: str) -> dict[str, Any]:
        """Account details, properties, tariff rates and time-of-use windows."""
        data = await self.async_query(_ACCOUNT, {"n": account_number})
        account = data["account"]
        account["supply_points"] = [e["node"] for e in data["supplyPoints"]["edges"]]
        return account

    async def async_measurements(
        self,
        property_id: str,
        start: datetime,
        end: datetime,
        frequency: str = THIRTY_MIN_INTERVAL,
        direction: str = CONSUMPTION,
    ) -> list[dict[str, Any]]:
        """Every interval in the window, following pagination."""
        filters = [
            {
                "electricityFilters": {
                    "readingFrequencyType": frequency,
                    "readingDirection": direction,
                }
            }
        ]
        rows: list[dict[str, Any]] = []
        after: str | None = None
        while True:
            conn = (
                await self.async_query(
                    _MEASUREMENTS,
                    {
                        "pid": property_id,
                        "s": start.isoformat(),
                        "e": end.isoformat(),
                        "f": filters,
                        "after": after,
                    },
                )
            )["property"]["measurements"]
            rows.extend(edge["node"] for edge in conn["edges"])
            if not conn["pageInfo"]["hasNextPage"]:
                return rows
            after = conn["pageInfo"]["endCursor"]
