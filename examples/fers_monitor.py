"""Read an A5202 through FERSlib. Opening stops any active acquisition."""

import argparse
import json
from dataclasses import asdict

from dune_dscs.devices.fers import A5202


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", help="eth:<IPv4>[:tdl:<chain>:<node>] or usb:<PID or index>")
    parser.add_argument("--library", help="Path to the installed CAEN FERSlib shared library")
    args = parser.parse_args()
    with A5202(args.path, library=args.library) as board:
        result = {
            "library_version": board.library_version,
            "board": asdict(board.board_info()),
            "hv_status": asdict(board.hv_status()),
        }
        for quantity in ("board_temperature_c", "fpga_temperature_c", "hv_temperature_c",
                         "bias_voltage_v", "voltage_v", "current_limit_ma", "current_ma"):
            result[quantity] = board.read(quantity)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
