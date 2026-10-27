"""IPMI-over-LAN (RMCP) BMC emulator.

Speaks real IPMI 1.5 session-based LAN protocol (ping, channel auth
capabilities, session challenge/activate, SDR repository, sensor reading)
so it can be pointed at by sensor_readers.IPMIReader / a real IPMI client.
Only advertises AUTH_TYPE_NONE, so no password/session crypto needs to be
implemented - this is a test double, not a production BMC.

Each configured sensor just returns a fresh random integer in [1, 100] on
every GetSensorReading request.

Usage:
    python3 ipmi_emulator.py --host 0.0.0.0 --port 6230 --sensors "Temp1,Fan1,Voltage1"

Note: real IPMI uses UDP port 623, which requires root to bind. Use a
high port (as in devices.yaml's examples) for unprivileged local testing.
"""
import argparse
import random
import socket
import struct

import pyipmi.msgs as msgs
import pyipmi.sdr as sdr
from pyipmi.interfaces.rmcp import (
    RmcpMsg, AsfPing, RMCP_CLASS_ASF, RMCP_CLASS_IPMI,
)
from pyipmi.interfaces.ipmb import IpmbHeaderReq, IpmbHeaderRsp, encode_ipmb_msg

NETFN_APP = 0x06
NETFN_SENSOR_EVENT = 0x04

CMD_GET_DEVICE_ID = 0x01
CMD_GET_CHANNEL_AUTH_CAP = 0x38
CMD_GET_SESSION_CHALLENGE = 0x39
CMD_ACTIVATE_SESSION = 0x3A
CMD_SET_SESSION_PRIV_LEVEL = 0x3B
CMD_CLOSE_SESSION = 0x3C
CMD_RESERVE_DEVICE_SDR_REPO = 0x22
CMD_GET_DEVICE_SDR = 0x21
CMD_GET_SENSOR_READING = 0x2D

CC_OK = 0x00
CC_REQUESTED_RECORD_NOT_PRESENT = 0xCB
CC_INVALID_SENSOR_NUMBER = 0xCB


def build_full_sensor_record(record_id, sensor_number, name):
    """Build an IPMI "Full Sensor Record" SDR entry for `name`.

    Linear factors are M=1, B=0, linearization=linear, so the raw byte we
    hand back in GetSensorReading IS the engineering value - no unit
    conversion needed on either side.
    """
    body = bytearray()
    body += bytes([0x20, 0x00, sensor_number])   # owner_id, owner_lun, sensor_number
    body += bytes([0x00, 0x00])                  # entity id/instance
    body += bytes([0x00])                        # initialization
    body += bytes([0x00])                        # capabilities
    body += bytes([0x0B])                        # sensor type: other units-based
    body += bytes([0x01])                        # event/reading type: threshold
    body += struct.pack('<H', 0)                 # assertion mask
    body += struct.pack('<H', 0)                 # deassertion mask
    body += struct.pack('<H', 0)                 # discrete reading mask
    body += bytes([0x00])                        # units_1: unsigned, no rate/modifier/pct
    body += bytes([0x00])                        # units_2: base unit (unspecified)
    body += bytes([0x00])                        # units_3: modifier unit
    body += bytes([0x00])                        # linearization: linear
    body += bytes([0x01, 0x00])                  # M=1, M_tol=0
    body += bytes([0x00, 0x00, 0x00])             # B=0, B_acc=0, acc/accexp=0
    body += bytes([0x00])                        # Rexp/Bexp = 0
    body += bytes([0x00])                        # analog characteristics flags
    body += bytes([0, 100, 1, 100, 0])            # nominal, normal_max, normal_min, sensor_max, sensor_min
    body += bytes([0, 0, 0, 0, 0, 0])             # thresholds (unr,ucr,unc,lnr,lcr,lnc)
    body += bytes([0, 0])                         # hysteresis
    body += bytes([0, 0])                         # reserved
    body += bytes([0x00])                         # oem
    name_bytes = name.encode('ascii')[:31]
    body += bytes([0xC0 | len(name_bytes)]) + name_bytes  # device ID string (ASCII, type/length byte)

    header = struct.pack('<H', record_id) + bytes([0x51, sdr.SDR_TYPE_FULL_SENSOR_RECORD, len(body)])
    return bytes(header) + bytes(body)


class BMC:
    """Holds the emulated sensor set: SDR records + a sensor number -> name map."""

    def __init__(self, sensor_names):
        self.record_order = []
        self.records = {}          # record_id -> full record bytes
        self.sensor_names = {}     # sensor_number -> name

        for i, name in enumerate(sensor_names):
            record_id = i
            sensor_number = i + 1
            self.records[record_id] = build_full_sensor_record(record_id, sensor_number, name)
            self.record_order.append(record_id)
            self.sensor_names[sensor_number] = name

    def next_record_id(self, record_id):
        idx = self.record_order.index(record_id)
        if idx + 1 < len(self.record_order):
            return self.record_order[idx + 1]
        return 0xFFFF


def handle_command(bmc, netfn, cmdid, payload):
    """Return the response payload bytes (post-IPMB-header), or an int
    completion code for an error response."""

    if netfn == NETFN_APP and cmdid == CMD_GET_CHANNEL_AUTH_CAP:
        req = msgs.create_message(netfn, cmdid, None)
        msgs.decode_message(req, payload)
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.channel_number = req.channel.number
        rsp.support.none = 1  # only auth type we support - no crypto needed
        rsp.status.anonymous_login_enabled = 1
        return msgs.encode_message(rsp)

    if netfn == NETFN_APP and cmdid == CMD_GET_SESSION_CHALLENGE:
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.temporary_session_id = 0x00001000
        rsp.challenge_string = b'\x00' * 16
        return msgs.encode_message(rsp)

    if netfn == NETFN_APP and cmdid == CMD_ACTIVATE_SESSION:
        req = msgs.create_message(netfn, cmdid, None)
        msgs.decode_message(req, payload)
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.authentication.type = 0
        rsp.session_id = 0xBEEF0001
        rsp.initial_inbound_sequence_number = 1
        rsp.privilege_level.maximum_allowed = req.privilege_level.maximum_requested
        return msgs.encode_message(rsp)

    if netfn == NETFN_APP and cmdid == CMD_SET_SESSION_PRIV_LEVEL:
        req = msgs.create_message(netfn, cmdid, None)
        msgs.decode_message(req, payload)
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.privilege_level.new = req.privilege_level.requested
        return msgs.encode_message(rsp)

    if netfn == NETFN_APP and cmdid == CMD_CLOSE_SESSION:
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        return msgs.encode_message(rsp)

    if netfn == NETFN_APP and cmdid == CMD_GET_DEVICE_ID:
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.device_id = 0
        rsp.device_revision.device_revision = 1
        rsp.device_revision.provides_device_sdrs = 1
        rsp.firmware_revision.major = 1
        rsp.firmware_revision.device_available = 0
        rsp.firmware_revision.minor = 0
        rsp.ipmi_version = 0x51
        rsp.additional_support.sensor = 1
        rsp.additional_support.sdr_repository = 0
        rsp.additional_support.sel = 0
        rsp.additional_support.fru_inventory = 0
        rsp.additional_support.ipmb_event_receiver = 0
        rsp.additional_support.ipmb_event_generator = 0
        rsp.additional_support.bridge = 0
        rsp.additional_support.chassis = 0
        rsp.manufacturer_id = 0
        rsp.product_id = 0
        return msgs.encode_message(rsp)

    if netfn == NETFN_SENSOR_EVENT and cmdid == CMD_RESERVE_DEVICE_SDR_REPO:
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.reservation_id = 1
        return msgs.encode_message(rsp)

    if netfn == NETFN_SENSOR_EVENT and cmdid == CMD_GET_DEVICE_SDR:
        req = msgs.create_message(netfn, cmdid, None)
        msgs.decode_message(req, payload)
        record = bmc.records.get(req.record_id)
        if record is None:
            return CC_REQUESTED_RECORD_NOT_PRESENT
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.next_record_id = bmc.next_record_id(req.record_id)
        rsp.record_data = record[req.offset:req.offset + req.bytes_to_read]
        return msgs.encode_message(rsp)

    if netfn == NETFN_SENSOR_EVENT and cmdid == CMD_GET_SENSOR_READING:
        req = msgs.create_message(netfn, cmdid, None)
        msgs.decode_message(req, payload)
        name = bmc.sensor_names.get(req.sensor_number)
        if name is None:
            return CC_INVALID_SENSOR_NUMBER
        value = random.randint(1, 100)
        rsp = msgs.create_message(netfn | 1, cmdid, None)
        rsp.completion_code = CC_OK
        rsp.sensor_reading = value
        rsp.config.initial_update_in_progress = 0
        rsp.config.sensor_scanning_disabled = 0
        rsp.config.event_message_disabled = 0
        print(f" [ipmi] {name} (sensor #{req.sensor_number}) -> {value}")
        return msgs.encode_message(rsp)

    print(f" [!] Unhandled IPMI command netfn=0x{netfn:02x} cmdid=0x{cmdid:02x}")
    return None


def run(host, port, sensor_names):
    bmc = BMC(sensor_names)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"IPMI emulator listening on {host}:{port}")
    print(f"Sensors: {', '.join(sensor_names)}")

    out_seq = 0
    while True:
        pdu, addr = sock.recvfrom(4096)

        rmcp = RmcpMsg()
        try:
            sdu = rmcp.unpack(pdu)
        except Exception as e:
            print(f" [!] Bad RMCP packet from {addr}: {e}")
            continue

        if rmcp.class_of_msg == RMCP_CLASS_ASF:
            try:
                AsfPing().unpack(sdu)
            except Exception:
                continue
            # AsfPong.pack() in pyipmi only returns the inner data bytes
            # (its __init__ skips AsfMsg.__init__ and its pack() override
            # forgets the ASF header), so build the full ASF-framed pong
            # by hand: 8-byte ASF header + 16-byte pong data.
            pong_data = struct.pack('!IIBB6x', 4542, 0, 0x81, 0)
            asf_header = struct.pack('!IBBxB', 4542, 0x40, 0, len(pong_data))
            pong_pdu = RmcpMsg(RMCP_CLASS_ASF).pack(asf_header + pong_data, rmcp.seq_number)
            sock.sendto(pong_pdu, addr)
            continue

        if rmcp.class_of_msg != RMCP_CLASS_IPMI:
            continue

        # Session header: we only ever advertise AUTH_TYPE_NONE, so this is
        # always the fixed 10-byte no-auth form. The client doesn't validate
        # the session-layer sequence number / session id on responses (only
        # the IPMB-level header below is checked), so we don't track them.
        try:
            _auth_type, _seq, _session_id, data_len = struct.unpack('!BIIB', sdu[:10])
            ipmb_bytes = sdu[10:10 + data_len]
            req_header = IpmbHeaderReq(data=ipmb_bytes)
            cmd_payload = ipmb_bytes[6:-1]
        except Exception as e:
            print(f" [!] Bad IPMI session/IPMB framing from {addr}: {e}")
            continue

        result = handle_command(bmc, req_header.netfn, req_header.cmdid, cmd_payload)
        if result is None:
            continue

        rsp_payload = bytes([result]) if isinstance(result, int) else result

        rsp_header = IpmbHeaderRsp()
        rsp_header.rq_sa = req_header.rq_sa
        rsp_header.rs_sa = req_header.rs_sa
        rsp_header.netfn = req_header.netfn + 1
        rsp_header.rq_lun = req_header.rq_lun
        rsp_header.rs_lun = req_header.rs_lun
        rsp_header.rq_seq = req_header.rq_seq
        rsp_header.cmdid = req_header.cmdid
        ipmb_rsp = encode_ipmb_msg(rsp_header, rsp_payload)

        out_sdu = struct.pack('!BIIB', 0, 0, 0, len(ipmb_rsp)) + ipmb_rsp
        out_pdu = RmcpMsg(RMCP_CLASS_IPMI).pack(out_sdu, out_seq)
        out_seq = (out_seq + 1) % 254
        sock.sendto(out_pdu, addr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="IPMI-over-LAN BMC emulator (random 1-100 sensor values)")
    parser.add_argument("--host", default="0.0.0.0", help="address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=6230, help="UDP port to bind (default: 6230; real IPMI is 623, which needs root)")
    parser.add_argument("--sensors", default="Temp1,Fan1,Voltage1", help="comma-separated sensor names")
    args = parser.parse_args()

    sensor_names = [s.strip() for s in args.sensors.split(",") if s.strip()]

    try:
        run(args.host, args.port, sensor_names)
    except KeyboardInterrupt:
        print("\nStopped")
