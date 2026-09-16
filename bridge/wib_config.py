import yaml

class WIBConfig:
    def __init__(self, filename="wibs.yaml"):
        with open(filename) as f:
            self.config = yaml.safe_load(f)

    def get_wibs(self):
        return self.config["wibs"]
