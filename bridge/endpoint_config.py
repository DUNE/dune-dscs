import yaml

class ENDPOINT:
    def __init__(self, filename="endpoint.yaml"):
      with open(filename) as f:
          self.config = yaml.safe_load(f) or {}
      endpoint_info = self.get_endpoint_info()
      self.IP = endpoint_info["IP"]
      self.port = endpoint_info["port"]
      self.server_name = endpoint_info["server_name"]   
      self.register_namespace = endpoint_info["register_namespace"]
      self.ignition_endpoint = f"opc.tcp://{self.IP}:{self.port}/freeopcua/server"

    def get_endpoint_info(self):
        return self.config.get("endpoint") or []


