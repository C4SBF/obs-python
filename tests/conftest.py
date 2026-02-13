from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(__file__))
_SRC_PATH = os.path.join(_REPO_ROOT, "src")

if _SRC_PATH not in sys.path:
    sys.path.insert(0, _SRC_PATH)

pytest_plugins = [
    "tests.fixtures",
    "tests.discovery.bacnet.fixtures",
]
