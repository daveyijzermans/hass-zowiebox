"""Constants for the ZowieBox integration."""

DOMAIN = "zowiebox"

CONF_NAME = "name"
CONF_HOST = "host"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_SCAN_INTERVAL = 5  # seconds; matches the box's own web UI cadence
MIN_SCAN_INTERVAL = 2
MAX_SCAN_INTERVAL = 60

# How long the HDMI signal must be continuously present before the
# "steady" binary sensor reports on (debounces source switches / blips).
STEADY_SECONDS = 5

WORKMODE_ENCODER = 0
WORKMODE_DECODER = 1
WORKMODE_LABELS = {WORKMODE_ENCODER: "Encoder", WORKMODE_DECODER: "Decoder"}

NDI_SERVICE_TYPE = "_ndi._tcp.local."

PLATFORMS = ["binary_sensor", "select", "sensor", "button"]
