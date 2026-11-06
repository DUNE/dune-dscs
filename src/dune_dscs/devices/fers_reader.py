"""A5202 telemetry reader for the shared OPC UA bridge."""

import logging
import time
from dataclasses import asdict

from .fers import A5202, FersError

_LOGGER = logging.getLogger(__name__)


class FersReader:
    """Keep one board connection open and return typed telemetry per poll."""

    STATUS_FIELDS = frozenset({"read_ok", "last_error", "last_success_unix_s"})
    QUANTITIES = (
        "board_temperature_c", "fpga_temperature_c", "hv_temperature_c",
        "bias_voltage_v", "voltage_v", "current_limit_ma", "current_ma",
    )

    def __init__(self, path, *, library=None, detector_temperature=False):
        self.board = A5202(path, library=library)
        self._opened = False
        self.quantities = self.QUANTITIES
        if detector_temperature:
            self.quantities += ("detector_temperature_c",)
        self.initial_values = {
            "pid": 0, "fers_code": 0, "pcb_revision": 0, "model_code": "",
            "model_name": "", "form_factor": 0, "channels": 0,
            "fpga_firmware": 0, "mcu_firmware": 0, "library_version": "",
            **dict.fromkeys(self.quantities, 0.0),
            "hv_enabled": False, "hv_ramping": False,
            "hv_overcurrent": False, "hv_overvoltage": False,
            "read_ok": False, "last_error": "Not polled", "last_success_unix_s": 0.0,
        }
        self._last_success = 0.0

    def read(self):
        """Return a complete poll, or error status without partial readings.

        A read failure keeps the existing handle. It does not reopen the board
        and repeat FERS_OpenDevice's acquisition stop during the next poll.
        """
        try:
            if not self._opened:
                self.board.open()
                self._opened = True
            values = asdict(self.board.board_info())
            values["library_version"] = self.board.library_version
            for quantity in self.quantities:
                values[quantity] = self.board.read(quantity)
            values.update({f"hv_{name}": value
                           for name, value in asdict(self.board.hv_status()).items()})
        except (FersError, OSError, RuntimeError, ValueError) as error:
            return {"read_ok": False, "last_error": str(error),
                    "last_success_unix_s": self._last_success}
        self._last_success = time.time()
        return {**values, "read_ok": True, "last_error": "",
                "last_success_unix_s": self._last_success}

    def close(self):
        """Release the board without changing the HV output."""
        try:
            self.board.close()
        except FersError as error:
            _LOGGER.error("Could not close A5202 at %s: %s", self.board.path, error)
        else:
            self._opened = False
