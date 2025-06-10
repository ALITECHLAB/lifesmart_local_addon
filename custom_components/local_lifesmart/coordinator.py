"""Data coordinator for Local Lifesmart integration."""
from datetime import timedelta

import logging
from typing import Any, Dict, List
import asyncio
from asyncio import Lock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import LifeSmartAPI

_LOGGER = logging.getLogger(__name__)

class LifeSmartCoordinator(DataUpdateCoordinator):
    """Class to manage fetching data from Lifesmart API."""

    def __init__(
        self, 
        hass: HomeAssistant, 
        api: LifeSmartAPI,
        scan_interval: int = 60000 # Default to 30 seconds
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="LifeSmart",
            update_interval=timedelta(milliseconds=scan_interval),
        )
        self.api = api
        self._available = True
        self._lock = Lock()
        self._push_task = None
        
    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from API."""
        try:
            # Start push listener if not already running
            if self._push_task is None or self._push_task.done():
                self._push_task = asyncio.create_task(self._listen_for_updates())
                
            # Fetch all devices
            devices_data = await self.api.discover_devices()
            self._available = True
            return devices_data
        except Exception as err:
            self._available = False
            raise UpdateFailed(f"Error communicating with API: {err}")
    
    async def _listen_for_updates(self):
        # Add better error recovery
        retry_count = 0
        max_retries = 5
        retry_delay = 1
        
        while True:
            try:
                # Reset the device lookup on each reconnection
                device_lookup = {}
                if self.data and "msg" in self.data:
                    device_lookup = {device.get("me"): device for device in self.data.get("msg", [])}
                
                while True:
                    update = await self.api.get_state_updates()
                    # Reset retry count on successful update
                    retry_count = 0
                    
                    # Process the update
                    if update:
                        await self.async_refresh()
                    
            except Exception as e:
                retry_count += 1
                _LOGGER.error("Error in push update listener (attempt %s/%s): %s", 
                             retry_count, max_retries, str(e))
                
                # Close socket to ensure clean reconnection
                if hasattr(self.api, '_socket') and self.api._socket:
                    try:
                        await self.api._socket.close()
                    except Exception as close_error:
                        _LOGGER.debug("Error closing socket: %s", close_error)
                    self.api._socket = None
                
                # If we've exceeded max retries, stop trying
                if retry_count >= max_retries:
                    _LOGGER.error("Max retries exceeded for push updates, giving up")
                    break
                    
                # Exponential backoff for retries
                await asyncio.sleep(retry_delay * (2 ** (retry_count - 1)))
            
        # Cleanup when exiting the loop
        self._push_task = None
        self.devices = {}
        self.device_info = {}
        self._available = True
        
    @property 
    def available(self) -> bool:
        """Return if coordinator is available."""
        return self._available
    def get_api(self) -> LifeSmartAPI:
        """Return the API instance."""
        return self.api
    
    async def _async_get_device_data(self, device_id: str,timout: float=1.0) -> Dict[str, Any]:
        
        """Fetch single device data from API with retry logic."""
        async with self._lock:
            for attempt in range(3):  # Try 3 times
                try:
                    device_data = await asyncio.wait_for(
                        self.api.discover_devices_by_id(device_id,timout),
                        timeout=timout  
                    )
                    
                    formatted_data = {
                        "msg": []
                    }
                    
                    if isinstance(device_data, dict) and "msg" in device_data:
                        formatted_data["msg"].extend(device_data["msg"])
                        
                    return formatted_data

                except asyncio.TimeoutError:
                    if attempt == 2:  # Last attempt
                        raise UpdateFailed(f"Error communicating with API for device {device_id}: timed out")
                    await asyncio.sleep(1)  # Wait before retry
                    
                except Exception as err:
                    raise UpdateFailed(f"Error communicating with API for device {device_id}: {err}")

    async def _async_update_data(self , timout: float=1.0) -> Dict[str, Any]:
        """Fetch data from API with retry logic."""
       
        for attempt in range(3):  # Try 3 times
            try:
                devices = await asyncio.wait_for(
                    self.api.get_devices(),
                    timeout=timout 
                )
                
                formatted_data = {
                    "msg": []
                }
                
                if isinstance(devices, dict):
                    for device_id, device_data in devices.items():
                        if isinstance(device_data, dict):
                            formatted_data["msg"].append(device_data)
                            
                return formatted_data

            except asyncio.TimeoutError:
                if attempt == 2:  # Last attempt
                    raise UpdateFailed("Error communicating with API: timed out")
                await asyncio.sleep(1)  # Wait before retry
                
            except Exception as err:
                raise UpdateFailed(f"Error communicating with API: {err}")


            
    def get_device(self, device_id: str) -> Dict[str, Any]:
        """Get device data by ID."""
        return self.devices.get(device_id, {})

    def get_devices(self) -> Dict[str, Any]:
        """Get all devices data."""
        return self.devices

    def get_device_info(self, device_id: str) -> Dict[str, Any]:
        """Get device info by ID."""
        return self.device_info.get(device_id, {})

    async def async_set_device_state(self, device_id: str, state: Dict[str, Any], time_out: float = 2.0) -> None:
        """Set device state with improved error handling."""
        if not self.available:
            return
        try:
            result = await self.hass.async_add_executor_job(
                self.api.set_device_state, device_id, state, time_out
            )
            _LOGGER.debug("Device state set successfully: %s", result)
            await self.async_refresh()
            return
        except asyncio.TimeoutError:
            _LOGGER.error("Timeout occurred while setting device state")
            raise UpdateFailed("Timeout occurred while setting device state")

        except Exception as err:
            _LOGGER.error("Error setting device state: %s", err)
            raise
