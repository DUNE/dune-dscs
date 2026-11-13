"""PX4 monitoring objects verified against the lab PDU and PDU2-MIB."""

import json
import time
from pathlib import Path

from pysnmp.proto.api import v2c

ROOT = (1, 3, 6, 1, 4, 1, 13742, 6)


class PduMonitoring:
    def __init__(self, model):
        self.model = model
        self.profile = json.loads(Path(__file__).with_name("pdu_monitoring.json").read_text())
        self.fixed, self.readings, self.variables = {}, {}, {}
        states = {int(k): v for k, v in self.profile["state_names"].items()}
        self.started = time.monotonic()
        self.on_time = {n: 0.0 for n in model.outlets}
        self.on_since = {n: None for n in model.outlets}
        for item in self.profile["identity"]:
            value = len(model.outlets) if item["name"].startswith("outletCount_") else item["value"]
            name = "OutletCount" if item["name"].startswith("outletCount_") else item["name"]
            mapping = {int(k): v for k, v in item.get("values", {}).items()}
            self.add(name, item["oid"], item["type"], value, values=mapping)
        self.add("UptimeSeconds", "1.3.6.1.2.1.1.3.0", "Double", None, unit="s", scale=.01)
        self.readings[self.oid("1.3.6.1.2.1.1.3.0")] = ({}, 0, "uptime")
        for outlet in model.outlets:
            self.add(f"Outlet{outlet}On", ROOT + (4, 1, 2, 1, 3, 1, outlet), "Boolean", None,
                     values={7: True, 8: False})
            self.readings[ROOT + (4, 1, 2, 1, 3, 1, outlet)] = ({}, outlet, "state")
            self.add(f"Outlet{outlet}Name", ROOT + (3, 5, 3, 1, 3, 1, outlet), "String", f"Outlet {outlet}")
        for sensor in self.profile["sensors"]:
            outlets = model.outlets if sensor["family"] == "outlet" else (0,)
            for outlet in outlets:
                label = (f"Outlet{outlet}" if outlet else f'{sensor["family"].title()}{sensor["channel"]}')
                name = label + "_" + sensor["name"]
                for field, suffix, kind in (("available", "Available", "Boolean"), ("state", "State", "String")):
                    oid = sensor[field + "_oid"].format(outlet=outlet)
                    self.add(name + suffix, oid, kind, sensor[field],
                             values={1: True, 2: False} if field == "available" else states)
                    if field == "state" and sensor["family"] == "outlet" and sensor["sensor"] == 14:
                        self.readings[self.oid(oid)] = (sensor, outlet, "state")
                for field in ("unit", "digits"):
                    scalar = v2c.Integer32(sensor["unit_id"]) if field == "unit" else v2c.Unsigned32(sensor["digits"])
                    self.fixed[self.oid(sensor[field+"_oid"].format(outlet=outlet))] = scalar
                # Discrete sensors have a state, not a meaningful numeric reading.
                if sensor["available"] != 1 or sensor["sensor"] in (14, 46, 47):
                    continue
                oid = sensor["value_oid"].format(outlet=outlet)
                self.add(name, oid, "Double", None, unit=sensor["unit"], scale=10**-sensor["digits"])
                self.readings[self.oid(oid)] = (sensor, outlet, "value")
                if sensor["sensor"] == 24 and "signed_value_oid" in sensor:
                    signed = sensor["signed_value_oid"].format(outlet=outlet)
                    self.variables[name]["source"] = signed
                    self.readings[self.oid(signed)] = (sensor, outlet, "signed")

    @staticmethod
    def oid(value):
        return tuple(map(int, value.split("."))) if isinstance(value, str) else tuple(value)

    def add(self, name, oid, kind, value, unit="", scale=1, values=None):
        oid = self.oid(oid)
        settings = {"source": ".".join(map(str, oid)), "type": kind}
        if unit:
            settings["unit"] = unit
        if scale != 1:
            settings["scale"] = scale
        if values:
            settings["values"] = values
        self.variables[name] = settings
        if value is not None:
            self.fixed[oid] = v2c.OctetString(value) if isinstance(value, str) else v2c.Integer32(value)

    def elapsed(self):
        return self.model.telemetry.elapsed() if self.model.telemetry else time.monotonic()-self.started

    def power_changed(self, outlet, enabled):
        now = self.elapsed()
        previous = self.on_since[outlet]
        if previous is not None:
            self.on_time[outlet] += now-previous
        self.on_since[outlet] = now if enabled else None

    def active_seconds(self, outlet):
        since = self.on_since[outlet]
        return self.on_time[outlet] + (self.elapsed()-since if since is not None else 0)

    def contains(self, oid):
        return oid in self.fixed or oid in self.readings

    def read(self, oid):
        if oid not in self.readings:
            return self.fixed[oid]
        sensor, outlet, field = self.readings[oid]
        if field == "uptime":
            return v2c.TimeTicks(int(self.elapsed()*100) % (2**32))
        if field == "state":
            return v2c.Integer32(7 if self.model.outlets[outlet] else 8)
        kind = sensor["sensor"]
        if kind in (8, 9):
            seconds = self.active_seconds(outlet) if outlet else sum(self.active_seconds(n) for n in self.model.outlets)
            value = seconds * (.35 * 120) / 3600 if self.model.telemetry else 0
        elif outlet and not self.model.outlets[outlet]:
            value = 0
        else:
            current = .35 if outlet else .02 + .35 * sum(self.model.outlets.values())
            nominal, amplitude = {
                1: (current, .05), 2: (current*1.2, .05), 4: (120, 2),
                5: (120*current*.98, 2), 6: (120*current, 2), 7: (.98, .015),
                23: (60, .2), 24: (0, 2), 29: (2, .8), 35: (.98, .015),
                51: (1.8, .1), 57: (2.8, .3), 58: (10, 1), 59: (.8, .1),
            }[kind]
            value = (self.model.telemetry.analog(nominal, amplitude, outlet*60+kind)
                     if self.model.telemetry else nominal)
        if field == "signed":
            return v2c.Integer32(round(value * 10**sensor["digits"]))
        # The unsigned object is undefined for negative readings; use SignedValue for phase.
        return v2c.Unsigned32(round(max(0, value) * 10**sensor["digits"]) % (2**32))

    def values(self):
        return {oid: self.read(oid) for oid in self.fixed.keys() | self.readings.keys()}
