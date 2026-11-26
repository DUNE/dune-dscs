#!/usr/bin/env python3
"""Check from the bridge host that every emulator in hosts.txt answers as a new WIB emulator.

Sends one WIB GetSWVersion request to every host/port and counts:
  new-WIB    answered correctly (dune_dscs WIB emulator)
  other/old  something answered, but not the new WIB protocol (e.g. the old zmq_emulator.py)
  no-answer  nothing answered within --timeout

Exit code 0 only if every port on every host is new-WIB.

    ~/DSCS/dscs-env/bin/python new_bridge/check_fleet.py [--per-host 100] [--verbose]
"""

import argparse
import asyncio
from pathlib import Path

import zmq
import zmq.asyncio

from dune_dscs.emulator.protocols._generated import wib_pb2 as wib

HERE = Path(__file__).resolve().parent


async def probe(context, address, port, timeout, limiter):
    async with limiter:
        socket = context.socket(zmq.REQ)
        socket.setsockopt(zmq.LINGER, 0)
        socket.connect(f"tcp://{address}:{port}")
        try:
            command = wib.Command()
            command.cmd.Pack(wib.GetSWVersion())
            await socket.send(command.SerializeToString())
            reply = await asyncio.wait_for(socket.recv(), timeout)
            try:
                return "new" if wib.GetSWVersion.Version.FromString(reply).version else "other"
            except Exception:  # noqa: BLE001 - any undecodable reply is "not the new emulator"
                return "other"
        except asyncio.TimeoutError:
            return "none"
        finally:
            socket.close()


def ranges(ports):
    """[5555, 5556, 5557, 5600] -> '5555-5557,5600'"""
    parts, start = [], None
    for index, port in enumerate(ports):
        if start is None:
            start = port
        if index + 1 == len(ports) or ports[index + 1] != port + 1:
            parts.append(str(start) if start == port else f"{start}-{port}")
            start = None
    return ",".join(parts)


async def main(args):
    hosts = []
    for line in args.hosts.read_text().splitlines():
        parts = line.split("#", 1)[0].split()
        if parts:
            hosts.append((parts[0], parts[1]))
    ports = list(range(args.base_port, args.base_port + args.per_host))
    context = zmq.asyncio.Context()
    limiter = asyncio.Semaphore(200)
    ok = True
    total = 0
    for name, address in hosts:
        results = await asyncio.gather(*(probe(context, address, port, args.timeout, limiter) for port in ports))
        counts = {kind: results.count(kind) for kind in ("new", "other", "none")}
        total += counts["new"]
        good = counts["new"] == len(ports)
        ok &= good
        print(f"{'OK ' if good else 'BAD'} {name:8s} {address:16s} new-WIB {counts['new']:3d}  "
              f"other/old {counts['other']:3d}  no-answer {counts['none']:3d}")
        if args.verbose and not good:
            for kind in ("other", "none"):
                bad = [p for p, r in zip(ports, results) if r == kind]
                if bad:
                    print(f"      {kind}: ports {ranges(bad)}")
    context.term()
    print(f"{total}/{len(hosts) * len(ports)} emulators answer as new WIB emulators.")
    return 0 if ok else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hosts", type=Path, default=HERE / "hosts.txt")
    parser.add_argument("--base-port", type=int, default=5555)
    parser.add_argument("--per-host", type=int, default=100)
    parser.add_argument("--timeout", type=float, default=2, help="seconds per request (default 2)")
    parser.add_argument("--verbose", action="store_true", help="list failing ports")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
