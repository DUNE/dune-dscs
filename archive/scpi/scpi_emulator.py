"""SCPI-over-TCP ("SCPI-RAW") instrument emulator.

Speaks the plain-text, newline-terminated command/response style used by
SCPI-RAW instruments (the same "just open a TCP socket and send ASCII
queries" transport common on bench multimeters/power supplies/etc, distinct
from GPIB/USB-TMC/VXI-11), so it can be pointed at by
sensor_readers.SCPIReader / any real SCPI-over-TCP client (netcat, PyVISA
with a TCPIP::...::SOCKET resource, etc).

Each configured command just returns a fresh random integer in [1, 100] on
every query. `*IDN?` is also answered, since many SCPI tools probe it.

Usage:
    python3 scpi_emulator.py --host 0.0.0.0 --port 5025 \\
        --commands "temp1=MEAS:TEMP?,volt1=MEAS:VOLT:DC?"
"""
import argparse
import random
import socket
import threading

IDN_REPLY = "SCPI Emulator,Model-1,SN0001,FW1.0"


def handle_command(cmd, commands):
    """commands: {UPPERCASE_COMMAND: sensor_name}. Returns a reply string,
    or None if the command expects no reply (matches real instruments,
    which stay silent on non-query commands)."""
    upper = cmd.upper()

    if upper == "*IDN?":
        return IDN_REPLY
    if not upper.endswith("?"):
        # A non-query command (e.g. *RST, *CLS) - real instruments act on
        # it and reply nothing.
        return None

    name = commands.get(upper)
    if name is None:
        print(f" [!] Unknown SCPI command: {cmd!r}")
        return '-113,"Undefined header"'

    value = random.randint(1, 100)
    print(f" [scpi] {name} ({cmd}) -> {value}")
    return str(value)


def handle_client(conn, addr, commands):
    print(f" [scpi] client connected: {addr}")
    buf = b""
    with conn:
        conn.settimeout(60)
        while True:
            try:
                chunk = conn.recv(4096)
            except socket.timeout:
                print(f" [scpi] client {addr} idle timeout, closing")
                break
            except OSError:
                break
            if not chunk:
                break

            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                cmd = line.decode("ascii", errors="replace").strip()
                if not cmd:
                    continue
                reply = handle_command(cmd, commands)
                if reply is not None:
                    try:
                        conn.sendall((reply + "\n").encode("ascii"))
                    except OSError:
                        break
    print(f" [scpi] client disconnected: {addr}")


def run(host, port, commands):
    """commands: {UPPERCASE_COMMAND: sensor_name}"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(5)
    print(f"SCPI emulator listening on {host}:{port}")
    for cmd, name in commands.items():
        print(f"  {name} -> {cmd}")

    while True:
        conn, addr = sock.accept()
        t = threading.Thread(target=handle_client, args=(conn, addr, commands), daemon=True)
        t.start()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SCPI-over-TCP instrument emulator (random 1-100 values)")
    parser.add_argument("--host", default="0.0.0.0", help="address to bind (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5025, help="TCP port to bind (default: 5025, the common SCPI-RAW port)")
    parser.add_argument(
        "--commands",
        default="temp1=MEAS:TEMP?,volt1=MEAS:VOLT:DC?",
        help="comma-separated name=SCPI_QUERY pairs",
    )
    args = parser.parse_args()

    commands = {}
    for pair in args.commands.split(","):
        pair = pair.strip()
        if not pair:
            continue
        name, cmd = pair.split("=", 1)
        commands[cmd.strip().upper()] = name.strip()

    try:
        run(args.host, args.port, commands)
    except KeyboardInterrupt:
        print("\nStopped")
