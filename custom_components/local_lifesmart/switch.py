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
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    """Set up LifeSmart switches with improved error handling."""
    data = hass.data[DOMAIN][config_entry.entry_id]
    api = data["api_manager"].api
    coordinator = data["coordinator"]
    
    # Ensure coordinator has completed at least one update
    if not coordinator.last_update_success:
        await coordinator.async_config_entry_first_refresh()
    
    switches = []
    if coordinator.data and "msg" in coordinator.data:
        for device in coordinator.data["msg"]:
            if device.get("devtype") in SUPPORTED_SWITCH_TYPES:
                device_data = device.get("data", {})
                for channel in ["L1", "L2", "L3"]:
                    if channel in device_data:
                        try:
                            channel_data = device_data[channel]
                            channel_name = channel_data.get('name', channel).replace('{$EPN}', '').strip()
                            name = f"{device.get('name', 'Switch')} {channel_name}"
                            
                            switch = LifeSmartSwitch(
                                coordinator=coordinator,
                                api=api,
                                device=device,
                                idx=channel,
                                name=name.strip()
                            )
                            switches.append(switch)
                            _LOGGER.debug("Added switch: %s", switch.entity_id)
                        except Exception as ex:
                            _LOGGER.error("Error setting up switch for device %s channel %s: %s", 
                                         device.get("me"), channel, str(ex))

    if switches:
        async_add_entities(switches)
        _LOGGER.info("Added %d LifeSmart switches", len(switches))
    else:
        _LOGGER.info("No LifeSmart switches found")

class LifeSmartSwitch(CoordinatorEntity, SwitchEntity):
    def __init__(self, coordinator, api, device, idx, name):
        """Initialize the switch."""
        super().__init__(coordinator)
        self._api = api
        self._device = device
        self._idx = idx
        self._attr_name = name
        self._device_id = device['me']
        
        device_type = device.get('devtype')
        hub_id = device.get('agt', '')
        
        self.entity_id = f"{DOMAIN}.{generate_entity_id(device_type, hub_id, self._device_id, idx)}"
        self._attr_unique_id = f"lifesmart_switch_{self._device_id}_{idx}"
        
        initial_state = device.get("data", {}).get(idx, {}).get("v", 0)
        self._state = bool(initial_state)

    @property
    def available(self):
        """Return True if entity is available."""
        return self.coordinator.last_update_success

    @property
    def is_on(self):
        """Return true if device is on."""
        # More efficient state lookup using device_id directly
        if self.coordinator.data and "msg" in self.coordinator.data:
            for device in self.coordinator.data["msg"]:
                if device.get("me") == self._device_id:
                    state = device.get("data", {}).get(self._idx, {}).get("v", 0)
                    return bool(state)
        return self._state

    async def async_turn_on(self, **kwargs):
        """Turn the switch on."""
        await self._send_command(1)
        # No need to request refresh as push updates will handle this
        # But keep as fallback with a small delay
        await asyncio.sleep(0.5)  # Small delay to allow push update to arrive
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs):
        """Turn the switch off."""
        await self._send_command(0)
        # No need to request refresh as push updates will handle this
        # But keep as fallback with a small delay
        await asyncio.sleep(0.5)  # Small delay to allow push update to arrive
        await self.coordinator.async_request_refresh()

    async def _send_command(self, value: int):
        """Send command to device with improved error handling."""
        args = {
            "tag": "m",
            "me": self._device_id,
            "idx": self._idx,
            "type": VAL_TYPE_ON if value == 1 else VAL_TYPE_OFF,
            "val": value
        }
        try:
            response = await self._api.send_command("ep", args, CMD_SET, 2)
            if response.get("code") == 0:
                # Update local state immediately for faster UI response
                self._state = bool(value)
                self.async_write_ha_state()
                return True
            else:
                _LOGGER.error("Error in response: %s", response.get("msg", "Unknown error"))
                return False
        except Exception as ex:
            _LOGGER.error("Error sending command: %s", str(ex))
            self._available = False  # This attribute isn't initialized
            self.async_write_ha_state()
            return False
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
