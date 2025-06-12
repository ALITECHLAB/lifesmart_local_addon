"""Platform for LifeSmart switch integration."""
import logging
from datetime import timedelta
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.event import async_track_time_interval
from .const import DOMAIN, CMD_GET, CMD_SET, MANUFACTURER, VAL_TYPE_ONOFF
from . import generate_entity_id 

_LOGGER = logging.getLogger(__name__)

VAL_TYPE_ON = "0x81"
VAL_TYPE_OFF = "0x80"

SUPPORTED_SWITCH_TYPES = [
    "SL_SW_NS1",
    "SL_SW_NS2",
    "SL_SW_NS3",
    "SL_NATURE"
]
PORT_1 = "P2"
PORT_2 = "P3"
PORT_3 = "P4"

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LifeSmart switches."""
    api = hass.data[DOMAIN][config_entry.entry_id].api
    devices_data = await api.discover_devices()
    
    switches = []
    if isinstance(devices_data, dict) and "msg" in devices_data:
        for device in devices_data["msg"]:
            if device.get("devtype") in SUPPORTED_SWITCH_TYPES:
                data = device.get("data", {})
                for channel in ["L1", "L2", "L3"]:
                    if channel in data:
                        channel_data = data[channel]
                        channel_name = channel_data.get('name', channel).replace('{$EPN}', '').strip()
                        name = f"{device.get('name', 'Switch')} {channel_name}"
                        switches.append(
                            LifeSmartSwitch(
                                api=api,
                                device=device,
                                idx=channel,
                                name=name.strip()
                            )
                        )

    async_add_entities(switches)

class LifeSmartSwitch(SwitchEntity):
    def __init__(self, api, device, idx, name):
        """Initialize the switch."""
        self._api = api
        self._device = device
        self._idx = idx
        self._attr_name = name
        self._available = True
        self._remove_tracker = None
        
        device_type = device.get('devtype')
        hub_id = device.get('agt', '')
        device_id = device['me']
        
        self.entity_id = f"{DOMAIN}.{generate_entity_id(device_type, hub_id, device_id, idx)}"
        self._attr_unique_id = f"lifesmart_switch_{device_id}_{idx}"
        
        initial_state = device.get("data", {}).get(idx, {}).get("v", 0)
        self._state = bool(initial_state)

    async def async_added_to_hass(self):
        """When entity is added to hass."""
        await self._async_update_state()
        
        # Set up periodic state updates
        self._remove_tracker = async_track_time_interval(
            self.hass,
            self._async_update_state,
            timedelta(seconds=1)
        )

    async def async_will_remove_from_hass(self):
        """When entity is removed from hass."""
        if self._remove_tracker:
            self._remove_tracker()

    @callback
    async def _async_update_state(self, *_):
        """Fetch state from device."""
        try:
            args = {
                "tag": "m",
                "me": self._device["me"],
                "idx": self._idx,
                "type": VAL_TYPE_ONOFF,
                "val": 0
            }
            response = await self._api.send_command("ep", args, CMD_GET)
            if response.get("code") == 0 and "msg" in response:
                new_state = response["msg"]["data"][self._idx]["v"]
                self._state = bool(new_state)
                self._available = True
                _LOGGER.debug(
                    "Switch %s state updated: %s (value=%s)", 
                    self.entity_id, 
                    "on" if self._state else "off",
                    new_state
                )
            self.async_write_ha_state()
        except Exception as ex:
            _LOGGER.error(f"Error updating switch state: {ex} device= {self._device} idx={self._idx}  ")
            self._available = False

    @property
    def available(self):
        """Return True if entity is available."""
        return self._available

    @property
    def is_on(self):
        """Return true if device is on."""
        return self._state

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device['me'])},
            name=self._attr_name,
            manufacturer=MANUFACTURER,
            model=self._device.get('devtype'),
            sw_version=self._device.get('epver'),
        )
    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        previous_state = self._state
        self._state = True
        self.async_write_ha_state()  # Immediate UI feedback
        
        success = await self._send_command(1)
        if not success:
            # Rollback UI state if command failed
            self._state = previous_state
            self.async_write_ha_state()
            _LOGGER.warning("Failed to turn on switch, UI state reverted")
    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        previous_state = self._state
        self._state = False
        self.async_write_ha_state()  # Immediate UI feedback
        
        success = await self._send_command(0)
        if not success:
            # Rollback UI state if command failed
            self._state = previous_state
            self.async_write_ha_state()
            _LOGGER.warning("Failed to turn off switch, UI state reverted")



    async def _send_command(self, value: int) -> bool:
        """Send command to device and return success status."""
        args = {
            "tag": "m",
            "me": self._device["me"],
            "idx": self._idx,
            "type": VAL_TYPE_ON if value == 1 else VAL_TYPE_OFF,
            "val": value
        }
        try:
            response = await self._api.send_command("ep", args, CMD_SET, 2)
            if response.get("code") == 0:
                self._available = True
                return True
            else:
                _LOGGER.error("Device command failed with code: %s", response.get("code"))
                self._available = False
                return False
        except Exception as ex:
            if "timed out" in str(ex).lower():
                # For timeouts, assume success (as per your current logic)
                _LOGGER.warning("Command timed out but may have succeeded: %s", str(ex))
                self._available = True
                return True
            else:
                _LOGGER.error("Error sending command: %s", str(ex))
                self._available = False
                return False