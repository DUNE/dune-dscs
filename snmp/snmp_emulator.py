"""SNMP (v1/v2c) agent emulator.

Speaks real SNMP GetRequest/GetResponse over UDP, using pysnmp's own PDU
classes to build/parse messages, so it can be pointed at by
sensor_readers.SNMPReader / any real SNMP client (snmpget, etc).

Each configured OID just returns a fresh random integer in [1, 100] on
every GetRequest.

Usage:
    python3 snmp_emulator.py --host 0.0.0.0 --port 16123 --community public \\
        --oids "sys_uptime=1.3.6.1.2.1.1.3.0,if_in_octets_1=1.3.6.1.2.1.2.2.1.10.1"

Note: real SNMP agents use UDP port 161, which requires root to bind. Use
a high port (as in devices.yaml's examples) for unprivileged local testing.
"""
import argparse
import random
import socket

from pyasn1.codec.ber import decoder, encoder
from pysnmp.proto.api import v2c


def run(host, port, community, oid_names):
    """oid_names: {oid_string: sensor_name}"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((host, port))
    print(f"SNMP emulator listening on {host}:{port} (community={community!r})")
    for oid, name in oid_names.items():
        print(f"  {name} -> {oid}")

    while True:
        data, addr = sock.recvfrom(4096)

        try:
            req_msg, _rest = decoder.decode(data, asn1Spec=v2c.Message())
        except Exception as e:
            print(f" [!] Bad SNMP packet from {addr}: {e}")
            continue

        req_community = str(v2c.apiMessage.get_community(req_msg))
        if req_community != community:
            print(f" [!] Wrong community {req_community!r} from {addr}")
            continue

        req_pdu = v2c.apiMessage.get_pdu(req_msg)

        var_binds = []
        for oid, _placeholder in v2c.apiPDU.get_varbinds(req_pdu):
            oid_str = str(oid)
            name = oid_names.get(oid_str)
            if name is None:
                var_binds.append((oid, v2c.NoSuchObject('')))
                print(f" [!] Unknown OID requested: {oid_str}")
                continue
            value = random.randint(1, 100)
            var_binds.append((oid, v2c.Integer32(value)))
            print(f" [snmp] {name} ({oid_str}) -> {value}")

        rsp_msg = v2c.apiMessage.get_response(req_msg)
        rsp_pdu = v2c.apiMessage.get_pdu(rsp_msg)
        v2c.apiPDU.set_varbinds(rsp_pdu, var_binds)

        sock.sendto(encoder.encode(rsp_msg), addr)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNMP agent emulator (random 1-100 OID values)")
    parser.add_argument("--host", default="0.0.0.0", help="address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=16123, help="UDP port to bind (default: 16123; real SNMP is 161, which needs root)")
    parser.add_argument("--community", default="public", help="SNMP community string (default: public)")
    parser.add_argument(
        "--oids",
        default="sys_uptime=1.3.6.1.2.1.1.3.0,if_in_octets_1=1.3.6.1.2.1.2.2.1.10.1",
        help="comma-separated name=oid pairs",
    )
    args = parser.parse_args()

    oid_names = {}
    for pair in args.oids.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, oid = pair.split("=", 1)
        oid_names[oid.strip()] = name.strip()

    try:
        run(args.host, args.port, args.community, oid_names)
    except KeyboardInterrupt:
        print("\nStopped")
