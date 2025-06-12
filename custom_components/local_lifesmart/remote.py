"""LifeSmart Remote Platform"""
import logging
from typing import Any, Dict, List
import time

from homeassistant.components import remote
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from . import generate_entity_id
from .const import DOMAIN, MANUFACTURER

_LOGGER = logging.getLogger(__name__)

SUPPORTED_REMOTE_TYPES = ["SL_P_IR"]

async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up LifeSmart Remote devices."""
    _LOGGER.info("Setting up LifeSmart remotes")
    api = hass.data[DOMAIN][config_entry.entry_id].api
    devices_data = await api.discover_devices()
    
    remotes: List[LifeSmartRemote] = []
    
    if isinstance(devices_data, dict) and "msg" in devices_data:
        remote_list = await api.get_remote_list()
        device_remotes = {}
        
        for device in devices_data["msg"]:
            if device.get("devtype") in SUPPORTED_REMOTE_TYPES:
                device_id = device["me"]
                if device_id not in device_remotes:
                    device_remotes[device_id] = {
                        "device": device,
                        "remotes": []
                    }
                
                for remote_data in remote_list:
                    if device_id in remote_data["remote"]["id"]:
                        device_remotes[device_id]["remotes"].append(remote_data)
        
        for device_id, data in device_remotes.items():
            remotes.append(
                LifeSmartRemote(
                    api=api,
                    device=data["device"],
                    remote_data_list=data["remotes"],
                    name=data["device"].get("name", "Remote")
                )
            )
    
    async_add_entities(remotes)

class LifeSmartRemote(remote.RemoteEntity):
    """LifeSmart Remote Entity."""


    def __init__(self, api, device: Dict[str, Any], remote_data_list: List[Dict[str, Any]], name: str):
        """Initialize the remote."""
        self._api = api
        self._device = device

        self._remote_data_list = remote_data_list
        self._attr_name = f"{name}_{device['me']}"
        self._available = True


        self._all_keys = {}
        self._remote_details = {}

        for remote_data in remote_data_list:
            remote_id = remote_data["remote"]["id"]
            self._remote_details[remote_id] = {
                "name": remote_data["remote"].get("name", ""),
                "category": remote_data["remote"].get("category", ""),
                "brand": remote_data["remote"].get("brand", ""),
                "keys": remote_data["keys"]
            }
            self._all_keys.update({key: remote_id for key in remote_data["keys"]})
        
      
        _LOGGER.info(f"Initializing LifeSmart remote: {self._attr_name} with ID: {self.entity_id}")

    @property
    def name(self) -> str:
        """Return the name of the remote."""
        return self._attr_name

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._available

    @property
    def supported_features(self) -> int:
        """Return the list of supported features."""
        return remote.RemoteEntityFeature.ACTIVITY

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return the state attributes."""
        attributes = {
            "agt": self._device.get("agt"),
            "me": self._device.get("me"),
            "devtype": self._device.get("devtype"),
            "remotes": self._remote_details,
            "all_commands": list(self._all_keys.keys())
        }

        return attributes

    async def async_send_command(self, command: List[str], **kwargs: Any) -> None:
        """Send commands remote_id to a device."""      
        for cmd in command:

            
            if "::" in cmd:
                remote_id, key = cmd.split("::")
                if remote_id in self._remote_details and key in self._remote_details[remote_id]["keys"]:
                    try:

                        await self._api.send_remote_key(remote_id, key)

                    except Exception as ex:

                        _LOGGER.error(f"Unexpected error sending command {key} to remote {remote_id}: {str(ex)}")
            else:
                if cmd in self._all_keys:
                    remote_id = self._all_keys[cmd]
                    try:
                        await self._api.send_remote_key(remote_id, cmd)
                    except Exception as ex:

                        _LOGGER.error(f"Error sending command {cmd} to remote {remote_id}: {str(ex)}")

        

        
# async def async_send_command(self, command: List[str], **kwargs: Any) -> None:
 #     """Send commands remote_id to a device."""

 #     for cmd in command:
 #         # New format: remote_id::command
 #         if "::" in cmd:
 #             remote_id, key = cmd.split("::")
 #             if remote_id in self._remote_details and key in self._remote_details[remote_id]["keys"]:
 #                 try:
 #                     await self._api.send_remote_key(remote_id, key)
 #                 except Exception as ex:
 #                     _LOGGER.error(f"Error sending command {key} to remote {remote_id}: {str(ex)}")
 #         # Maintain backwards compatibility with existing command format
 #         elif cmd in self._all_keys:
 #             remote_id = self._all_keys[cmd]
 #             try:
 #                 await self._api.send_remote_key(remote_id, cmd)
 #             except Exception as ex:
 #                 _LOGGER.error(f"Error sending command {cmd} to remote {remote_id}: {str(ex)}"