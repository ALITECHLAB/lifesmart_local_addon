"""LifeSmart API implementation."""
import socket
import json
import time
import hashlib
import struct
import logging
from typing import Any, Dict
from .const import API_PORT, REMARK, CMD_REPORT

_LOGGER = logging.getLogger(__name__)

class LifeSmartAPI:
    def __init__(self, host: str, model: str, token: str , timeout: int = 5):
        self.host = host
        self.model = model
        self.token = token
        self.sequence = 1
        self._socket = None
        self.timeout = timeout

    def _create_signature(self, obj: str, args: Dict[str, Any], ts: int) -> str:
        sorted_args = sorted(args.items())
        args_string = ','.join(f'{k}:{v}' for k, v in sorted_args)
        base_string = f"obj:{obj},{args_string},ts:{ts},model:{self.model},token:{self.token}"
        return hashlib.md5(base_string.encode()).hexdigest()

    def create_message(self, obj: str, args: Dict[str, Any], pkg_type: int) -> bytes:
        ts = int(time.time())
        sign = self._create_signature(obj, args, ts)

        body = {
            "sys": {
                "ver": 1,
                "sign": sign,
                "model": self.model,
                "ts": ts
            },
            "id": self.sequence,
            "obj": obj,
            "args": args
        }
        self.sequence += 1

        body_json = json.dumps(body).encode('utf-8')
        header = struct.pack('>2sHHI', 
                           REMARK.encode(),
                           0,
                           pkg_type,
                           len(body_json))

        return header + body_json

    async def send_command(self, obj: str, args: Dict[str, Any], pkg_type: int,timeout: float = 5) -> Dict[str, Any]:
        message = self.create_message(obj, args, pkg_type)
        
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(timeout)
            sock.sendto(message, (self.host, API_PORT))
            
            data, _ = sock.recvfrom(65535)
            response = json.loads(data[10:].decode('utf-8'))
            
            return response

    async def discover_devices(self):
        args = {"me": "2d02"}
        return await self.send_command("eps", args, 1)

    async def get_state_updates(self):
        if not self._socket:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._socket.bind(('0.0.0.0', API_PORT))
            self._socket.settimeout(None)

        try:
            data, _ = self._socket.recvfrom(65535)
            if len(data) > 10:
                message = json.loads(data[10:].decode('utf-8'))
                _LOGGER.debug("Received UDP message: %s", message)
                
                if 'msg' in message:
                    msg = message['msg']
                    if isinstance(msg, dict):
                        return {
                            'me': msg.get('me'),
                            'idx': msg.get('idx'),
                            'val': msg.get('data', {}).get('v', msg.get('val')),
                            'type': msg.get('type')
                        }
                    
        except Exception as e:
            _LOGGER.error("Error receiving state update: %s", str(e))
            if self._socket:
                self._socket.close()
                self._socket = None
        return None
    async def get_remote_list(self) -> Dict[str, Any]:
        """Retrieve IR remote list for devices."""
        args = {
            "cmd": "getlist"
        }
        response = await self.send_command("spotremote", args, 3)
        
        if response and response.get("code") == 0 and "msg" in response:
            remote_list = response["msg"]
            all_keys = []
            
            for remote in remote_list:
                if "id" in remote:
                    keys = await self.get_remote_keys(remote["id"])
                    if keys and keys.get("code") == 0 and "msg" in keys:
                        all_keys.append({"remote": remote, "keys": keys["msg"]})
            return all_keys
        return response

    async def get_remote_keys(self, remote_id: str) -> Dict[str, Any]:
        """Retrieve IR remote keys for a specific device."""
        args = {
            "id": remote_id,
            "cmd": "getkeys"
        }
        return await self.send_command("spotremote", args, 3)

    async def send_remote_key(self, remote_id: str, key: str) -> Dict[str, Any]:
        """Send IR remote key command."""
        args = {
            "id": remote_id,
            "cmd": "sendkey",
            "key": key
        }
        return await self.send_command("spotremote", args, 3)
