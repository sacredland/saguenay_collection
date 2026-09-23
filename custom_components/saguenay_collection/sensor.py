import logging
import requests
from datetime import timedelta

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    CoordinatorEntity,
)

from .const import DOMAIN, BASE_URL

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(hours=1)


async def async_setup_entry(hass, config_entry, async_add_entities):
    city_id = config_entry.data["city"]
    civic_number = config_entry.data["civic_number"]
    street_id = config_entry.data["street_id"]
    schedules = config_entry.data["schedules"]

    coordinator = CollectionCoordinator(
        hass,
        city_id,
        civic_number,
        street_id,
        schedules,
    )

    await coordinator.async_config_entry_first_refresh()

    sensors = [
        CollectionSensor(coordinator, "compostage"),
        CollectionSensor(coordinator, "ordure"),
        CollectionSensor(coordinator, "récupération"),
    ]

    async_add_entities(sensors)


class CollectionCoordinator(DataUpdateCoordinator):
    """Fetch collection data."""

    def __init__(self, hass, city_id, civic_number, street_id, schedules):
        """Initialize the coordinator."""
        self.city_id = city_id
        self.civic_number = civic_number
        self.street_id = street_id
        self.schedules = schedules

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=SCAN_INTERVAL,
        )

    async def _async_update_data(self):
        """Fetch current schedules and collection dates."""

        def fetch_data():
            results = {}

            # First retrieve the CURRENT schedule IDs for this address.
            try:
                response = requests.post(
                    f"{BASE_URL}/collectesinfos",
                    data={"cle_batiment": self.street_id},
                    timeout=15,
                )
                response.raise_for_status()
                current_schedules = response.json()

                if not isinstance(current_schedules, list):
                    _LOGGER.error(
                        "Unexpected response from collectesinfos: %s",
                        current_schedules,
                    )
                    current_schedules = []

            except (requests.exceptions.RequestException, ValueError) as err:
                _LOGGER.error(
                    "Unable to refresh Saguenay collection schedules: %s",
                    err,
                )

                # Fall back to schedules saved during configuration.
                current_schedules = self.schedules

            for schedule in current_schedules:
                schedule_type = schedule.get(
                    "type_collecte", "Unknown"
                ).lower()

                horaire_id = schedule.get("horaire_id")

                if not horaire_id:
                    _LOGGER.warning(
                        "No horaire_id found for %s",
                        schedule_type,
                    )
                    continue

                _LOGGER.debug(
                    "Fetching %s using current horaire_id %s",
                    schedule_type,
                    horaire_id,
                )

                try:
                    response = requests.post(
                        f"{BASE_URL}/cedule",
                        data={"horaire_id": horaire_id},
                        timeout=15,
                    )

                    response.raise_for_status()
                    data = response.json()

                    # Saguenay may return JSON null when an old
                    # schedule no longer has a collection date.
                    if not isinstance(data, dict):
                        _LOGGER.warning(
                            "No collection data returned for %s "
                            "(horaire_id %s): %s",
                            schedule_type,
                            horaire_id,
                            data,
                        )
                        continue

                    date_collecte = data.get("date_collecte")

                    if not date_collecte:
                        _LOGGER.warning(
                            "No date_collecte returned for %s "
                            "(horaire_id %s)",
                            schedule_type,
                            horaire_id,
                        )
                        continue

                    results[schedule_type] = date_collecte

                except requests.exceptions.RequestException as err:
                    _LOGGER.error(
                        "Error fetching data for %s "
                        "(horaire_id %s): %s",
                        schedule_type,
                        horaire_id,
                        err,
                    )

                except ValueError as err:
                    _LOGGER.error(
                        "Error parsing JSON for %s "
                        "(horaire_id %s): %s",
                        schedule_type,
                        horaire_id,
                        err,
                    )

            _LOGGER.debug(
                "Saguenay collection results: %s",
                results,
            )

            return results

        return await self.hass.async_add_executor_job(fetch_data)


class CollectionSensor(CoordinatorEntity, SensorEntity):
    """Saguenay collection sensor."""

    def __init__(self, coordinator, collection_type):
        super().__init__(coordinator)
        self._collection_type = collection_type

    @property
    def name(self):
        """Return the name of the sensor."""
        return (
            f"Saguenay "
            f"{self._collection_type.capitalize()} Schedule"
        )

    @property
    def state(self):
        """Return the state of the sensor."""
        return self.coordinator.data.get(self._collection_type)

    @property
    def unique_id(self):
        """Return a unique ID for the sensor."""
        return (
            f"saguenay_collection_"
            f"{self._collection_type}_"
            f"{self.coordinator.street_id}"
        )

    @property
    def device_class(self):
        """Return the device class."""
        return "timestamp"
