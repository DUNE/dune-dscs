"""Use the same local modules as the existing bridge and emulator scripts."""

import sys
from pathlib import Path

ARCHIVE = Path(__file__).resolve().parents[1] / "archive"
sys.path.insert(0, str(ARCHIVE))
sys.path.insert(0, str(ARCHIVE / "wib" / "protobuf"))
sys.path.insert(0, str(ARCHIVE / "bridge"))
