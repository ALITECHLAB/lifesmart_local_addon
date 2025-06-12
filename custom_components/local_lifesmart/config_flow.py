"""Config flow for LifeSmart Local integration."""
import voluptuous as vol
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_TOKEN
from homeassistant.core import callback
import homeassistant.helpers.config_validation as cv
from .const import DOMAIN , DEFAULT_MODEL,DEFAULT_TOKEN
from .api import LifeSmartAPI
import ipaddress

_LOGGER = logging.getLogger(__name__)

def validate_host(host):
    """Validate that the host is a valid IP address or hostname."""
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        if len(host) > 253 or not all(len(part) <= 63 for part in host.split(".")):
            raise vol.Invalid("Invalid hostname")
        return host

def validate_token(token):
    """Validate token format."""
    if not isinstance(token, str) or len(token) != 24:
        raise vol.Invalid("Token must be 24 characters long")
    return token

DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required("model", default=DEFAULT_MODEL): str,
        vol.Required(CONF_TOKEN, default=DEFAULT_TOKEN): str,
    }
)

class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for LifeSmart integration."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        _LOGGER.debug("Initializing options flow handler")

    async def async_step_init(self, user_input=None):
        """Handle options flow."""
        _LOGGER.debug("Processing options flow init step")
        if user_input is not None:
            _LOGGER.debug("Saving options: %s", user_input)
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({})
        )

@config_entries.HANDLERS.register(DOMAIN)
class LifeSmartConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for LifeSmart Local."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_PUSH

    def __init__(self):
        """Initialize the config flow."""
        _LOGGER.debug("Initializing LifeSmart config flow")
        self._errors = {}
        self.config_entry = None

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        _LOGGER.debug("Creating options flow handler for entry: %s", config_entry.entry_id)
        return OptionsFlowHandler(config_entry)

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        _LOGGER.debug("Starting async_step_user with input: %s", user_input)
        errors = {}

        if user_input is not None:
            try:
                # Additional validation before creating API instance
                if not 1 <= len(user_input[CONF_HOST]) <= 253:
                    errors["base"] = "invalid_host"
                    raise vol.Invalid("Invalid host length")

                if not 1 <= len(user_input["model"]) <= 50:
                    errors["base"] = "invalid_model"
                    raise vol.Invalid("Invalid model length")

                _LOGGER.debug("Attempting to connect to LifeSmart hub at %s", user_input[CONF_HOST])
                api = LifeSmartAPI(
                    host=user_input[CONF_HOST],
                    model=user_input["model"],
                    token=user_input[CONF_TOKEN],
                    timeout=30
                )
                
                # Test the connection
                _LOGGER.debug("Starting device discovery")
                devices = await api.discover_devices()
                if devices:
                    _LOGGER.debug("Devices found: %s", devices)
                    return self.async_create_entry(
                        title="LifeSmart Hub",
                        data=user_input
                    )
                else:
                    _LOGGER.debug("No devices found")
                    errors["base"] = "no_devices"
                    
            except vol.Invalid as e:
                _LOGGER.debug("Validation error: %s", str(e))
                if "base" not in errors:
                    errors["base"] = "invalid_config"
            except Exception as e:
                _LOGGER.debug("Connection failed with error: %s", str(e))
                errors["base"] = "cannot_connect"

        _LOGGER.debug("Showing configuration form with errors: %s", errors)
        return self.async_show_form(
            step_id="user",
            data_schema=DATA_SCHEMA,
            errors=errors
        )

    async def async_step_import(self, user_input=None):
        """Handle import from configuration.yaml."""
        _LOGGER.debug("Starting async_step_import with input: %s", user_input)
        return await self.async_step_user(user_input)