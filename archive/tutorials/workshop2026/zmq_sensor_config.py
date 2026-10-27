import yaml


class ZMQSensorConfig:

    def __init__(self, filename="zmq_sensors.yaml"):
        with open(filename) as f:
            self.config = yaml.safe_load(f) or {}

    def get_voltages(self):
        return self.config.get("voltages") or {}

    def get_temperatures(self):
        return self.config.get("temperatures") or {}

