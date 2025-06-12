"""Platform for LifeSmart sensor integration."""
import logging
from datetime import timedelta
from typing import Any, Dict, Optional, List
import asyncio
import aiohttp
import json
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.const import UnitOfTemperature, PERCENTAGE
from .const import DOMAIN, CMD_GET, MANUFACTURER
from . import generate_entity_id
_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL_SECONDS = 240
MAX_RETRY_ATTEMPTS = 3
BASE_RETRY_DELAY = 1

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    _LOGGER.debug("Setting up LifeSmart sensors")
    
    api = hass.data[DOMAIN][config_entry.entry_id].api
    try:
        devices_data: Dict[str, Any] = await api.discover_devices()
    except aiohttp.ClientError as e:
        _LOGGER.error(f"Network error during device discovery: {str(e)}")
        return
    except asyncio.TimeoutError:
        _LOGGER.error("Timeout while discovering devices")
        return
    except Exception as e:
        _LOGGER.error(f"Unexpected error during device discovery: {str(e)}")
        return
    
    sensors: List[SensorEntity] = []
    if isinstance(devices_data, dict) and "msg" in devices_data:
        for device in devices_data["msg"]:
            try:
                if device.get("devtype") == "SL_NATURE":
                    if "data" in device and "T" in device["data"]:
                        _LOGGER.debug(f"Found temperature sensor in {device['name']}")
                        sensors.append(
                            LifeSmartTemperatureSensor(
                                api=api,
                                device=device,
                                idx="T"
                            )
                        )
                elif device.get("devtype") == "SL_P" and "data" in device and "P8" in device["data"]:
                    _LOGGER.debug(f"Found battery sensor in {device['name']}")
                    sensors.append(
                        LifeSmartBatterySensor(
                            api=api,
                            device=device,
                            idx="P8"
                        )
                    )
            except KeyError as e:
                _LOGGER.error(f"Missing required device data: {str(e)}")
                continue
            except ValueError as e:
                _LOGGER.error(f"Invalid device data format: {str(e)}")
                continue

    _LOGGER.debug(f"Adding {len(sensors)} sensors")
    async_add_entities(sensors)

class LifeSmartBaseSensor(SensorEntity):
    _api: Any
    _device: Dict[str, Any]
    _idx: Optional[str]
    _remove_tracker: Optional[callable]
    _attr_device_info: DeviceInfo
    
    def __init__(self, api: Any, device: Dict[str, Any], idx: Optional[str] = None) -> None:
        self._api = api
        self._device = device
        self._idx = idx
        self._remove_tracker = None


        try:
            self._attr_device_info = DeviceInfo(
                identifiers={(DOMAIN, device['me'])},
                name=device.get('name', 'LifeSmart Sensor'),
                manufacturer=MANUFACTURER,
                model=device.get('devtype', 'Unknown'),
                sw_version=device.get('epver', 'Unknown')
            )
        except KeyError as e:
            _LOGGER.error(f"Missing required device info field: {str(e)}")
            raise

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await self._async_update()
        
        self._remove_tracker = async_track_time_interval(
            self.hass,
            self._async_update,
            timedelta(seconds=UPDATE_INTERVAL_SECONDS)
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity is removed from hass."""
        if self._remove_tracker:
            self._remove_tracker()

    async def _retry_with_backoff(self, func, *args, **kwargs):
        """Retry a function with exponential backoff."""
        for attempt in range(MAX_RETRY_ATTEMPTS):
            try:
                return await func(*args, **kwargs)
            except aiohttp.ClientError as e:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise
                _LOGGER.error(f"Network error on attempt {attempt + 1}: {str(e)}")
            except asyncio.TimeoutError:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise
                _LOGGER.error(f"Timeout on attempt {attempt + 1}")
            except json.JSONDecodeError as e:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise
                _LOGGER.error(f"Invalid JSON response on attempt {attempt + 1}: {str(e)}")
            except Exception as e:
                if attempt == MAX_RETRY_ATTEMPTS - 1:
                    raise
                _LOGGER.error(f"Unexpected error on attempt {attempt + 1}: {str(e)}")
            
            delay = BASE_RETRY_DELAY * (2 ** attempt)
            _LOGGER.debug(f"Retrying in {delay} seconds")
            await asyncio.sleep(delay)

    @callback
    async def _async_update(self, *_: Any) -> None:
        """Abstract method to be implemented by child classes."""
        raise NotImplementedError

class LifeSmartTemperatureSensor(LifeSmartBaseSensor):
    _attr_name: str
    _attr_unique_id: str
    _attr_native_value: Optional[float]
    _attr_native_unit_of_measurement: str
    
    def __init__(self, api: Any, device: Dict[str, Any], idx: str) -> None:
        super().__init__(api, device, idx)
        try:
            self._attr_name = f"{device.get('name', 'Temperature Sensor')}"
            self._attr_unique_id = f"lifesmart_temp_{device['me']}"
            self._attr_native_value = device.get("data", {}).get(idx, {}).get("v")
            self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
            device_type = device.get('devtype')
            hub_id = device.get('agt', '')
            device_id = device['me']
            self._idx = idx
            self.entity_id = f"{DOMAIN}.{generate_entity_id(device_type, hub_id, device_id, idx)}"

        except KeyError as e:
            _LOGGER.error(f"Missing required temperature sensor field: {str(e)}")
            raise

    @callback
    async def _async_update(self, *_: Any) -> None:
        """Fetch temperature from device."""
        args: Dict[str, Any] = {
            "tag": "m",
            "me": self._device["me"],
            "idx": self._idx,
            "type": "T",
            "val": 0
        }
        
        try:
            response: Dict[str, Any] = await self._retry_with_backoff(
                self._api.send_command,
                "ep",
                args,
                CMD_GET
            )
            _LOGGER.debug(f"Received response: {response}")
            
            if response.get("code") == 0 and "msg" in response:
                try:
                    temp_value = response["msg"]["data"]["T"]["v"]
                    self._attr_native_value = float(temp_value)
                    _LOGGER.debug(f"Temperature updated for {self._attr_name}: {self._attr_native_value}°C")
                except (KeyError, ValueError) as e:
                    _LOGGER.error(f"Invalid temperature data format: {str(e)}")
            else:
                _LOGGER.error(f"Invalid response code: {response.get('code')}")
            
            self.async_write_ha_state()
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Network error updating temperature sensor: {str(e)}")
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout updating temperature sensor")
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Invalid JSON response updating temperature sensor: {str(e)}")
        except Exception as e:
            _LOGGER.error(f"Unexpected error updating temperature sensor: {str(e)}")

class LifeSmartBatterySensor(LifeSmartBaseSensor):
    _attr_name: str
    _attr_unique_id: str
    _attr_native_value: Optional[int]
    _attr_native_unit_of_measurement: str
    
    def __init__(self, api: Any, device: Dict[str, Any] , idx: str) -> None:
        super().__init__(api, device, idx)
        try:
            self._attr_name = f"{device.get('name', 'MINS Curtain')} Battery"
            self._attr_unique_id = f"lifesmart_battery_{device['me']}"
            self._attr_native_unit_of_measurement = PERCENTAGE
            self._attr_native_value = device.get("data", {}).get("P8", {}).get("v")
            device_type = device.get('devtype')
            hub_id = device.get('agt', '')
            device_id = device['me']
            self._idx = idx
            self.entity_id = f"{DOMAIN}.{generate_entity_id(device_type, hub_id, device_id, idx)}"
        except KeyError as e:
            _LOGGER.error(f"Missing required battery sensor field: {str(e)}")
            raise

    @callback
    async def _async_update(self, *_: Any) -> None:
        """Fetch battery level."""
        args: Dict[str, Any] = {
            "me": self._device["me"],
            "idx": self._idx
        }
        try:
            response: Dict[str, Any] = await self._retry_with_backoff(
                self._api.send_command,
                "ep",
                args,
                CMD_GET
            )
            _LOGGER.debug(f"Battery response: {response}")
            
            if response.get("code") == 0 and "msg" in response:
                try:
                    battery_level = response["msg"]["data"]["P8"]["v"]
                    self._attr_native_value = battery_level
                    _LOGGER.debug(f"Battery level updated for {self._attr_name}: {self._attr_native_value}%")
                except (KeyError, ValueError) as e:
                    _LOGGER.error(f"Invalid battery data format: {str(e)}")
            else:
                _LOGGER.error(f"Invalid response code: {response.get('code')}")
            
            self.async_write_ha_state()
        except aiohttp.ClientError as e:
            _LOGGER.error(f"Network error updating battery sensor: {str(e)}")
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout updating battery sensor")
        except json.JSONDecodeError as e:
            _LOGGER.error(f"Invalid JSON response updating battery sensor: {str(e)}")
        except Exception as e:
            _LOGGER.error(f"Unexpected error updating battery sensor: {str(e)}")
