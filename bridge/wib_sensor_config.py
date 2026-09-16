import yaml


class WIBSensorConfig:
    """Loads the WIB protobuf-field -> array-length maps used to build each
    WIB's OPC UA nodes, from wib_sensors.yaml.

    Kept separate from wib_config.py/wibs.yaml (the per-WIB host/port
    list), since that file's format is shared by other scripts.
    """

    def __init__(self, filename="wib_sensors.yaml"):
        with open(filename) as f:
            self.config = yaml.safe_load(f) or {}

    def get_voltages(self):
        return self.config.get("voltages") or {}

    def get_temperatures(self):
        return self.config.get("temperatures") or {}

    def get_version(self):
        return self.config.get("version") or {}

    def get_timestamp(self):
        return self.config.get("timestamp") or {}

    def get_timing_status(self):
        return self.config.get("timing_status") or {}

    def get_peek(self):
        return self.config.get("peek") or {}
