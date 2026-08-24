"""Constants for the Octopus Energy NZ integration."""

from datetime import timedelta

DOMAIN = "octopus_nz"

CONF_ACCOUNT_NUMBER = "account_number"

# Kraken's NZ tenant. Each Octopus country runs its own tenant on its own host;
# the UK endpoint does not serve NZ accounts.
API_URL = "https://api.oenz-kraken.energy/v1/graphql/"

# Metered data arrives from the lines company roughly two days late, so polling
# harder does not surface anything sooner.
UPDATE_INTERVAL = timedelta(hours=1)

# How far back to reach on the first run. Octopus retains about 12 months.
INITIAL_BACKFILL_DAYS = 365

STATISTIC_CONSUMPTION = f"{DOMAIN}:electricity_consumption"
STATISTIC_COST = f"{DOMAIN}:electricity_cost"

# Kraken's time-of-use bucket names mapped to enum states. Octopus NZ shows
# these to customers as Night, Off-peak and Peak; the display strings come from
# translations, so the state itself stays a stable slug.
BUCKET_SLUGS = {
    "OFFPEAK": "night",
    "SHOULDER": "off_peak",
    "PEAK": "peak",
}

THIRTY_MIN_INTERVAL = "THIRTY_MIN_INTERVAL"
DAY_INTERVAL = "DAY_INTERVAL"
CONSUMPTION = "CONSUMPTION"
GENERATION = "GENERATION"
