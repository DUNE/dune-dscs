"""Use the same local modules as the existing bridge and emulator scripts."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "wib" / "protobuf"))
sys.path.insert(0, str(ROOT / "bridge"))
