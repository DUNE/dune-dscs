"""Use the same local modules as the existing bridge and emulator scripts."""

import ctypes as ct
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ARCHIVE = Path(__file__).resolve().parents[1] / "archive"
sys.path.insert(0, str(ARCHIVE))
sys.path.insert(0, str(ARCHIVE / "wib" / "protobuf"))
sys.path.insert(0, str(ARCHIVE / "bridge"))


@pytest.fixture
def sdk(tmp_path):
    compiler = shutil.which("cc")
    if not compiler:
        pytest.skip("A C compiler is required for the native FERSlib tests")
    source = Path(__file__).parent / "fixtures" / "fers_stub.c"
    library = tmp_path / "libcaenferslib.so"
    command = [compiler, "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror"]
    if include := os.environ.get("FERSLIB_INCLUDE_DIR"):
        command += ["-DFERSLIB_HEADER_CHECK", "-I", include]
    subprocess.run(command + [str(source), "-o", str(library)], check=True, capture_output=True)
    control = ct.CDLL(str(library))
    for name in ("stub_fail", "stub_model"):
        getattr(control, name).argtypes = [ct.c_int]
        getattr(control, name).restype = None
    control.stub_temperature.argtypes = [ct.c_float]
    control.stub_temperature.restype = None
    for name in ("stub_opened", "stub_closes", "stub_writes"):
        getattr(control, name).argtypes = []
        getattr(control, name).restype = ct.c_int
    return library, control



@pytest.fixture
def bridge(monkeypatch):
    monkeypatch.chdir(ARCHIVE / "bridge")
    spec = importlib.util.spec_from_file_location(
        "tested_bridge", ARCHIVE / "bridge/ignition_pybridge.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    context = module.context
    yield module
    context.destroy(linger=0)
