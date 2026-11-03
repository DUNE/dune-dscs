"""Use the same local modules as the existing bridge and emulator scripts."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "wib" / "protobuf"))
sys.path.insert(0, str(ROOT / "bridge"))
