"""Run one device without a fleet, control API or OPC UA server."""

import argparse
import asyncio

from .clock import ScaledRealClock
from .inventory import DeviceIdentity, Endpoint


async def run(args):
    if args.kind == "pdu":
        from .pdu import PduAgent
        listener = PduAgent(args.host, args.port, args.outlets, args.community)
    else:
        from .models import DaphneModel, WibModel
        from .protocols.daphne_zmq import DaphneZmqFleet
        from .protocols.wib_zmq import WibZmqFleet
        identity = DeviceIdentity(args.kind, args.kind, Endpoint("tcp", args.host, args.port))
        model_type, protocol = (DaphneModel, DaphneZmqFleet) if args.kind == "daphne" else (WibModel, WibZmqFleet)
        model = model_type(identity, ScaledRealClock(args.time_scale))
        await model.set_power(True)
        listener = protocol([model])
    try:
        await listener.start()
        print(f"{args.kind} emulator listening on {args.host}:{args.port}", flush=True)
        await asyncio.Event().wait()
    finally:
        await listener.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("pdu", "daphne", "wib"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--outlets", type=int, default=10)
    parser.add_argument("--community", default="private")
    parser.add_argument("--time-scale", type=float, default=0)
    args = parser.parse_args()
    if args.port is None:
        args.port = {"pdu": 1161, "daphne": 40001, "wib": 1234}[args.kind]
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
