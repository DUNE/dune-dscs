"""DAPHNE protobuf v2 request/reply handler."""

import itertools
import time

from google.protobuf.message import DecodeError

from .protocols._generated import daphneV3_high_level_confs_pb2 as pb


class Daphne:
    def __init__(self, telemetry=None):
        self.telemetry = telemetry
        self.sequence = itertools.count(1)
        self.thresholds = [0] * 40
        self.config = pb.ConfigureRequest()

    def reply(self, payload):
        request = pb.ControlEnvelopeV2()
        try:
            request.ParseFromString(payload)
        except DecodeError:
            return None
        if request.version != 2 or request.dir != pb.DIR_REQUEST:
            return None
        response = self.dispatch(request.type, request.payload)
        # correl_id identifies the request; timestamp_ns is monotonic time, not UTC.
        return pb.ControlEnvelopeV2(
            version=2, dir=pb.DIR_RESPONSE,
            type=request.type + 1 if request.type and not request.type & 1 else request.type,
            payload=response.SerializeToString() if response is not None else b"",
            task_id=request.task_id, msg_id=next(self.sequence),
            correl_id=request.msg_id, route=request.route, timestamp_ns=time.monotonic_ns(),
        ).SerializeToString()

    def dispatch(self, message_type, payload):
        if message_type == pb.MT2_CONFIGURE_FE_REQ:
            request = pb.ConfigureRequest()
            try:
                request.ParseFromString(payload)
                if any(not 0 <= channel.id < 40 for channel in request.channels):
                    raise ValueError("channel must be between 0 and 39")
                if any(not 0 <= afe.id < 5 or not 0 <= afe.attenuators <= 4095
                       or not 0 <= afe.v_bias <= 4095 for afe in request.afes):
                    raise ValueError("invalid AFE index or DAC value")
            except (DecodeError, ValueError) as error:
                return pb.ConfigureResponse(success=False, message=str(error))
            self.config.CopyFrom(request)
            threshold = (request.self_trigger_xcorr or request.self_trigger_threshold) & 0x0FFFFFFF
            for channel in request.channels:
                self.thresholds[channel.id] = threshold
            return pb.ConfigureResponse(success=True, message="Emulated configuration complete")
        if message_type == pb.MT2_READ_TRIGGER_COUNTERS_REQ:
            request = pb.ReadTriggerCountersRequest()
            try:
                request.ParseFromString(payload)
            except DecodeError:
                return pb.ReadTriggerCountersResponse(success=False, message="Invalid request")
            response = pb.ReadTriggerCountersResponse(success=True, message="OK")
            for channel in request.channels or range(40):
                if 0 <= channel < 40:
                    snapshot = response.snapshots.add(channel=channel, threshold=self.thresholds[channel])
                    if self.telemetry is not None:
                        snapshot.record_count = self.telemetry.counter(100 + channel + self.telemetry.seed % 100)
                        snapshot.busy_count = self.telemetry.counter(1 + channel % 5)
                        snapshot.full_count = self.telemetry.counter(.1)
            return response
        if message_type == pb.MT2_READ_TEST_REG_REQ:
            return pb.TestRegResponse(value=0xDEADBEEF, message="ok")
        if message_type == pb.MT2_READ_GENERAL_INFO_REQ:
            if self.telemetry is not None:
                # Synthetic ADC readings; there is no calibrated DAC-to-voltage model.
                values = {f"v_bias_{i}": self.telemetry.analog(50, .1, i) for i in range(5)}
                values.update(power_minus5v=self.telemetry.analog(-5, .02, 5),
                              power_plus2p5v=self.telemetry.analog(3.3, .02, 6),
                              power_ce=self.telemetry.analog(1.8, .01, 7),
                              temperature=self.telemetry.analog(28, .5, 8))
                return pb.GeneralInfo(**values)
            # Default fields are placeholders, not measured board telemetry.
            return pb.GeneralInfo()
        return None
