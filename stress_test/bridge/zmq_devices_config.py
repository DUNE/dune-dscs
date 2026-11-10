from pathlib import Path

import yaml


class ZMQDevicesConfig:
    def __init__(self, filename=None):
        if filename is None:
            filename = Path(__file__).with_name("zmq_devices.yaml")
        with open(filename) as f:
            self.config = yaml.safe_load(f)

    def get_devices(self):
        return self.config["zmqdevice"]
