"""Cross-language protocol constants; protocol.json is the canonical source."""
import json
from pathlib import Path
import re

_CONTRACT = json.loads(Path(__file__).with_suffix(".json").read_text())
HOST_PROTOCOL = _CONTRACT["host_protocol"]
LINK_PROTOCOL = _CONTRACT["link_protocol"]
HOST_TOKEN_PREFIX = _CONTRACT["host_token_prefix"]
DEVICE_TOKEN_PREFIX = _CONTRACT["device_token_prefix"]
WORKSPACE_ID_PATTERN = re.compile(_CONTRACT["workspace_id"]["pattern"])
RETIRED_WORKSPACE_FILES = tuple(_CONTRACT["retired_workspace_files"])
