import yaml


class DEVICES_ENDPOINT_CONFIG:
    def __init__(self, protocol, filename="endpoint.yaml"):
        with open(filename) as f:
            self.config = yaml.safe_load(f) or {}
        self.protocol = protocol
#        endpoint_info = self.get_devices_endpoint()
#        self.host = endpoint_info["host"]
#        self.port = endpoint_info["port"]
#        self.tpc = endpoint_info["tpc"]


    def get_devices_endpoint(self):
        devices_dic = {}
        for dev in list(self.config[self.protocol].keys()):
            if dev != "bridge":
                devices_dic[dev] = self.config[self.protocol][dev]
        print(devices_dic)
        return devices_dic