import yaml
import bridge_endpoint_config as bridge_endpoint_config
import devices_endpoint_config as devices_endpoint_config


class ENDPOINT:
    def __init__(self, filename="endpoint.yaml"):
      with open(filename) as f:
          self.config = yaml.safe_load(f) or {}
      self.bridge_endpoint_info = self.get_bridge_endpoint()
      #self.devices_endpoint_config = devices_endpoint_config()

    def get_bridge_endpoint(self):
        return bridge_endpoint_config.BRIDGE_ENDPOINT_CONFIG()

    def get_devices_endpoint(self, protocol):
        return devices_endpoint_config.DEVICES_ENDPOINT_CONFIG(protocol)


