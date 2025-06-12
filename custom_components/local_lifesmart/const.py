"""Constants for LifeSmart API specification v1.9."""
DOMAIN = "lifesmart"
MANUFACTURER = "LifeSmart"
# API Constants
DEFAULT_MODEL = "OD_ALI_TECH"
DEFAULT_TOKEN = "8SptZ2l2xnQlb8bSdT8mwA"

# API Protocol Constants
API_TIMEOUT = 10  # seconds
API_PORT = 12348
API_VERSION = 1
REMARK = "JL"
PLATFORMS = ["switch", "sensor","cover" , "remote"]
# Command Types
CMD_GET = 1    # Query command
CMD_SET = 3    # Control command
CMD_REPORT = 2 # Status report

# Value Types
VAL_TYPE_ONOFF = 0
VAL_TYPE_BRIGHTNESS = 1
VAL_TYPE_COLOR_TEMP = 2
VAL_TYPE_RGB = 3