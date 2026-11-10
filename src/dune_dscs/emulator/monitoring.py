"""Expand the example's PDU into the complete verified current-monitoring set."""

import argparse
from pathlib import Path

import yaml

from .pdu import Pdu


def expand(config, outlets):
    for device in config["devices"]:
        if device["kind"] == "pdu":
            device["variables"] = Pdu(outlets, full=True).monitoring.variables
            device["period"] = 30
    return config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config", help="base bridge YAML, such as examples/bridge-varying.yaml")
    parser.add_argument("--outlets", type=int, default=10)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    config = expand(yaml.safe_load(Path(args.config).read_text()), args.outlets)
    # Preserve any existing run or operator configuration.
    with Path(args.output).open("x") as file:
        yaml.safe_dump(config, file, sort_keys=False)


if __name__ == "__main__":
    main()
