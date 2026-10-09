"""Cross-language protocol constants; protocol.json is the canonical source."""
import json
from pathlib import Path
import re

_CONTRACT = json.loads(Path(__file__).with_suffix(".json").read_text())
HOST_PROTOCOL = _CONTRACT["host_protocol"]
WORKSPACE_ID_PATTERN = re.compile(_CONTRACT["workspace_id"]["pattern"])
RETIRED_WORKSPACE_FILES = tuple(_CONTRACT["retired_workspace_files"])
