# Octopus Energy NZ for Home Assistant

Brings Octopus Energy **New Zealand** consumption, tariff bands and costs into
Home Assistant, including a full year of backfilled history for the Energy
dashboard.

> This is for Octopus Energy NZ. The widely used
> [BottlecapDave integration](https://github.com/BottlecapDave/HomeAssistant-OctopusEnergy)
> is built against Octopus UK and will not work with an NZ account — each
> Octopus country runs a separate Kraken tenant with a different schema.

## What you get

**Energy dashboard.** Two long-term statistics, written against the time the
energy was actually used:

| Statistic | What |
|---|---|
| `octopus_nz:electricity_consumption` | kWh per hour |
| `octopus_nz:electricity_cost` | Cost per hour, priced per time-of-use band |

On first run these backfill up to 12 months, so the Energy dashboard has
history immediately rather than starting from empty.

**Sensors.**

| Sensor | What |
|---|---|
| Current tariff band | `Peak` / `Off-peak` / `Night`, right now |
| Current unit rate | $/kWh, right now |
| Daily charge | The plan's fixed daily supply charge |
| Last full day consumption | kWh for the most recent complete day |
| Latest interval consumption | The most recent metered half hour |
| Account balance | Your Octopus balance |

## The two-day lag, and what to do about it

Metered data comes from the lines company and arrives about **two days late**.
That is a property of New Zealand metering, not of this integration — no
retailer API gives live readings.

So:

- **Consumption and cost are history.** Excellent for the Energy dashboard and
  for understanding usage. Useless as an automation trigger.
- **The tariff sensors are live.** Bands are a property of the clock and are
  known in advance, so `Current tariff band` and `Current unit rate` are always
  correct right now. These are what you automate on.

Shift a load to the cheap band:

```yaml
automation:
  - alias: Heat water off-peak
    triggers:
      - trigger: state
        entity_id: sensor.octopus_nz_current_tariff_band
        to: "Night"
    actions:
      - action: water_heater.set_operation_mode
        target:
          entity_id: water_heater.hot_water
        data:
          operation_mode: performance
```

For live whole-house power you need local hardware — an optical pulse reader on
the meter's LED, or a Shelly EM with CT clamps.

## Install

### HACS

1. HACS → three-dot menu → **Custom repositories**
2. Add `https://github.com/corrin/ha-octopus-nz`, category **Integration**
3. Install **Octopus Energy NZ**, then restart Home Assistant
4. **Settings → Devices & Services → Add Integration → Octopus Energy NZ**

### Manual

Copy `custom_components/octopus_nz/` into your `config/custom_components/`
directory and restart.

## Configure

Sign in with the email and password you use for the Octopus Energy NZ app.

Then add the grid source: **Settings → Dashboards → Energy → Add consumption**,
and pick `octopus_nz:electricity_consumption`. Attach
`octopus_nz:electricity_cost` as its cost statistic.

### Why the password is stored

Kraken issues a customer no durable credential. `viewer.liveSecretKey` is null
on the NZ tenant, `obtainLongLivedRefreshToken` is reserved for third-party
organisations, and refresh tokens expire after a week. An integration that kept
only a refresh token would break the first time Home Assistant was off for a
week. The password is held in the config entry, like every other
username/password integration in Home Assistant.

## Cost accuracy

Costs are computed from the plan's own rates and time-of-use windows, both read
from your account, priced per half-hour interval, with the fixed daily charge
added once per day.

Verified against the Octopus web dashboard across six days: consumption and the
Night / Off-peak / Peak split matched to three decimal places, with no
unclassified energy.

The figure is an estimate of usage charges. It will not match a bill to the
cent — bills also carry prompt-payment discounts, credits and adjustments this
integration does not see.

## Notes

- Solar export is read where present (`GENERATION` direction).
- Multiple accounts on one login are supported; add the integration once per
  account.
- Diagnostics (Devices & Services → Octopus Energy NZ → Download diagnostics)
  dump the parsed tariff and windows, which is the fastest way to see what your
  plan actually looks like.

## Trademark

This is an unofficial integration, not affiliated with or endorsed by Octopus
Energy. The icon in `custom_components/octopus_nz/brand/` is Octopus Energy's
own mark, taken from their public site and used to identify which supplier this
integration talks to.

## License

MIT — the code. The brand icon remains the property of Octopus Energy.
