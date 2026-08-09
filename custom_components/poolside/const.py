"""Constants for the Poolside integration."""

from typing import Final

DOMAIN: Final = "poolside"
NAME: Final = "Poolside"
VERSION: Final = "0.1.44"

API_URL: Final = "https://api.poolside.cloud/api/jsonrpc/v1"
WS_URL: Final = "wss://gateway.poolside.cloud/websocket"

CONF_ACCESS_TOKEN: Final = "access_token"
CONF_TRANSPORT: Final = "transport"
TRANSPORT_CLOUD: Final = "cloud"

DEFAULT_SCAN_INTERVAL_SECONDS: Final = 300
HEARTBEAT_INTERVAL_SECONDS: Final = 240
PUSH_RECONNECT_MIN_SECONDS: Final = 1
PUSH_RECONNECT_MAX_SECONDS: Final = 60

PLATFORMS: Final = (
    "binary_sensor",
    "button",
    "calendar",
    "climate",
    "fan",
    "light",
    "number",
    "select",
    "sensor",
    "switch",
)
