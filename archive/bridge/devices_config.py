import yaml


class DevicesConfig:
    """Loads the IPMI/SNMP/SCPI/FERS device list for ignition_pybridge.py.

    Kept separate from WIBConfig/wibs.yaml since several other scripts
    already depend on that file's exact format.
    """

    def __init__(self, filename="devices.yaml"):
        with open(filename) as f:
            self.config = yaml.safe_load(f) or {}

    def get_ipmi_devices(self):
        return self.config.get("ipmi_devices") or []

    def get_snmp_devices(self):
        return self.config.get("snmp_devices") or []

    def get_scpi_devices(self):
        return self.config.get("scpi_devices") or []

    def get_fers_devices(self):
        return self.config.get("fers_devices") or []
