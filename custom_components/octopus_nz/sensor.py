"""Sensors for Octopus Energy NZ.

Two kinds live here, and they behave differently on purpose.

Metered figures (consumption) trail real time by about two days, so they are
only ever a report on the past. The tariff sensors are the opposite: the band
and unit rate are a property of the clock, known in advance and correct right
now, which is what makes them the useful trigger for load shifting.
"""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import OctopusNZConfigEntry
from .const import BUCKET_SLUGS, DOMAIN
from .coordinator import OctopusNZCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OctopusNZConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensors."""
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        LastFullDaySensor(coordinator),
        LatestIntervalSensor(coordinator),
        BalanceSensor(coordinator),
        CurrentBandSensor(coordinator),
        CurrentRateSensor(coordinator),
        DailyChargeSensor(coordinator),
    ]
    # Export rates only appear on the plan once the property is set up to
    # export, so their absence means there is nothing to show. A house that
    # gains solar later picks these up on the next reload.
    tariff = coordinator.data.tariff if coordinator.data else None
    if tariff and tariff.has_export:
        entities += [
            LastFullDayExportSensor(coordinator),
            LatestIntervalExportSensor(coordinator),
            CurrentExportRateSensor(coordinator),
        ]
    async_add_entities(entities)


def _device(coordinator: OctopusNZCoordinator) -> DeviceInfo:
    # One device per entry. An entry from before per-property entries keeps the
    # account-named device it always had.
    name = (
        f"Octopus NZ {coordinator.account_number}"
        if coordinator.legacy_ids
        else f"Octopus NZ {coordinator.property_label or coordinator.property_id}"
    )
    return DeviceInfo(
        identifiers={(DOMAIN, coordinator.key)},
        name=name,
        manufacturer="Octopus Energy NZ",
        model=(coordinator.data.tariff.name if coordinator.data and coordinator.data.tariff else None),
        entry_type=DeviceEntryType.SERVICE,
        configuration_url="https://octopusenergy.nz/dashboard",
    )


class OctopusNZEntity(CoordinatorEntity[OctopusNZCoordinator], SensorEntity):
    """Shared identity and device."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: OctopusNZCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.key}_{key}"
        self._attr_device_info = _device(coordinator)


class LastFullDaySensor(OctopusNZEntity):
    """Consumption for the most recent day with a complete set of intervals."""

    _attr_translation_key = "last_full_day"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "last_full_day")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.last_full_day if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        day = self.coordinator.data.last_full_day_date if self.coordinator.data else None
        return {"date": day.isoformat()} if day else None


class LatestIntervalSensor(OctopusNZEntity):
    """The most recent half-hour of metered consumption."""

    # No state_class: the value belongs to a half hour that ended two days ago,
    # so letting the recorder build statistics from it would file that energy
    # under the moment it was fetched. The statistics module handles this series
    # properly, against the interval's own timestamp.
    _attr_translation_key = "latest_interval"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "latest_interval")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.latest_interval if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        start = self.coordinator.data.latest_interval_start if self.coordinator.data else None
        return {"interval_start": start.isoformat()} if start else None


class LastFullDayExportSensor(OctopusNZEntity):
    """Export for the most recent day with a complete set of intervals."""

    _attr_translation_key = "last_full_day_export"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "last_full_day_export")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.last_full_day_export if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        day = self.coordinator.data.last_full_day_export_date if self.coordinator.data else None
        return {"date": day.isoformat()} if day else None


class LatestIntervalExportSensor(OctopusNZEntity):
    """The most recent half-hour of metered export."""

    # No state_class, for the same reason as LatestIntervalSensor.
    _attr_translation_key = "latest_interval_export"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "latest_interval_export")

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.latest_interval_export if self.coordinator.data else None

    @property
    def extra_state_attributes(self) -> dict[str, str] | None:
        start = self.coordinator.data.latest_interval_export_start if self.coordinator.data else None
        return {"interval_start": start.isoformat()} if start else None


class BalanceSensor(OctopusNZEntity):
    """Account balance."""

    _attr_translation_key = "balance"
    _attr_device_class = SensorDeviceClass.MONETARY
    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "balance")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.hass.config.currency

    @property
    def native_value(self) -> float | None:
        return self.coordinator.data.balance if self.coordinator.data else None


class DailyChargeSensor(OctopusNZEntity):
    """The plan's fixed daily supply charge."""

    _attr_translation_key = "daily_charge"
    _attr_device_class = SensorDeviceClass.MONETARY

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "daily_charge")

    @property
    def native_unit_of_measurement(self) -> str | None:
        return self.hass.config.currency

    @property
    def native_value(self) -> float | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        return tariff.daily_charge if tariff else None


class _LiveTariffSensor(OctopusNZEntity):
    """Reads the clock and the cached tariff, not the latest sync.

    The value is recomputed at the top of every minute, so a band boundary
    shows on time rather than at the next hourly sync. Polling cannot do this:
    BaseCoordinatorEntity pins should_poll to False, and its async_update would
    refresh the coordinator, calling Kraken on every poll.

    The tariff survives a failed sync in coordinator.data, so these stay
    available while one is cached.
    """

    _last_value: object = None

    @property
    def _now(self):
        return dt_util.now()

    @property
    def available(self) -> bool:
        return self.coordinator.data is not None and self.coordinator.data.tariff is not None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self._last_value = self.native_value
        self.async_on_remove(async_track_time_change(self.hass, self._async_tick, second=0))

    @callback
    def _async_tick(self, _now: datetime) -> None:
        value = self.native_value
        if value != self._last_value:
            self._last_value = value
            self.async_write_ha_state()


class CurrentBandSensor(_LiveTariffSensor):
    """Which time-of-use band applies right now."""

    _attr_translation_key = "current_band"
    _attr_device_class = SensorDeviceClass.ENUM

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "current_band")
        self._attr_options = list(BUCKET_SLUGS.values())

    @property
    def native_value(self) -> str | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        return tariff.slug_at(self._now) if tariff else None


class CurrentRateSensor(_LiveTariffSensor):
    """The unit rate applying right now."""

    _attr_translation_key = "current_rate"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "current_rate")

    @property
    def native_unit_of_measurement(self) -> str | None:
        currency = self.hass.config.currency or "NZD"
        return f"{currency}/{UnitOfEnergy.KILO_WATT_HOUR}"

    @property
    def native_value(self) -> float | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        return tariff.rate_at(self._now) if tariff else None

    @property
    def extra_state_attributes(self) -> dict[str, float] | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        if not tariff or not tariff.unit_rates:
            return None
        return {
            BUCKET_SLUGS.get(bucket, bucket): rate
            for bucket, rate in tariff.unit_rates.items()
        }


class CurrentExportRateSensor(_LiveTariffSensor):
    """What Octopus pays per kWh exported right now."""

    _attr_translation_key = "current_export_rate"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator: OctopusNZCoordinator) -> None:
        super().__init__(coordinator, "current_export_rate")

    @property
    def native_unit_of_measurement(self) -> str | None:
        currency = self.hass.config.currency or "NZD"
        return f"{currency}/{UnitOfEnergy.KILO_WATT_HOUR}"

    @property
    def native_value(self) -> float | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        return tariff.export_rate_at(self._now) if tariff else None

    @property
    def extra_state_attributes(self) -> dict[str, float] | None:
        tariff = self.coordinator.data.tariff if self.coordinator.data else None
        if not tariff or not tariff.export_rates:
            return None
        return {
            BUCKET_SLUGS.get(bucket, bucket): rate
            for bucket, rate in tariff.export_rates.items()
        }
