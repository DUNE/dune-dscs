"""Run one PDU, DAPHNE or WIB protocol emulator."""

import argparse
import asyncio

import zmq
import zmq.asyncio
from google.protobuf.message import DecodeError

from .telemetry import Telemetry
from .timing import Timing


async def run(args):
    timing = Timing.load(getattr(args, "timing", None), args.kind)
    seed = getattr(args, "seed", None)
    telemetry = Telemetry(seed=args.port if seed is None else seed,
                          period=getattr(args, "vary_period", 60)) if getattr(args, "vary", False) else None
    if args.kind == "pdu":
        from .pdu import PduAgent
        agent = PduAgent(args.host, args.port, args.outlets, args.community,
                         timing=timing, telemetry=telemetry)
        try:
            await agent.start()
            print(f"PDU listening on {args.host}:{args.port}", flush=True)
            await asyncio.Event().wait()
        finally:
            await agent.close()
        return

    from .daphne import Daphne
    from .protocols._generated import daphneV3_high_level_confs_pb2 as daphne_pb
    from .protocols._generated import wib_pb2 as wib_pb
    from .wib import Wib
    device = Daphne(telemetry=telemetry) if args.kind == "daphne" else Wib(telemetry=telemetry)
    with (
        zmq.asyncio.Context() as context,
        context.socket(zmq.ROUTER if args.kind == "daphne" else zmq.REP) as socket,
    ):
        socket.setsockopt(zmq.LINGER, 0)
        socket.bind(f"tcp://{args.host}:{args.port}")
        print(f"{args.kind} listening on {args.host}:{args.port}", flush=True)
        while True:
            frames = await socket.recv_multipart()
            if args.kind == "daphne":
                if len(frames) < 2:
                    continue
                try:
                    message_type = daphne_pb.ControlEnvelopeV2.FromString(frames[-1]).type
                    operation = next((name for name, value in vars(daphne_pb).items()
                                      if name.startswith("MT2_") and value == message_type), "unknown")
                    await timing.wait(operation)
                except DecodeError:
                    pass
                reply = device.reply(frames[-1])
                if reply is not None:
                    # Keep the routing frames, including the delimiter used by REQ clients.
                    await socket.send_multipart([*frames[:-1], reply])
            else:
                try:
                    operation = wib_pb.Command.FromString(frames[-1]).cmd.TypeName().split(".")[-1]
                    await timing.wait(operation)
                    reply = await device.reply(frames[-1])
                except (DecodeError, ValueError):
                    reply = b""
                # REP must reply before it can receive the next request, even after an error.
                await socket.send(reply)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("pdu", "daphne", "wib"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--outlets", type=int, default=10)
    parser.add_argument("--community", default="private")
    parser.add_argument("--timing", help="JSON response waits, in milliseconds, by native operation")
    parser.add_argument("--vary", action="store_true", help="enable synthetic sensor drift and counters")
    parser.add_argument("--vary-period", type=float, default=60, help="sensor drift period in seconds")
    parser.add_argument("--seed", type=int, help="repeatable per-device phase; defaults to the listening port")
    args = parser.parse_args()
    args.port = args.port if args.port is not None else {"pdu": 1161, "daphne": 40001, "wib": 1234}[args.kind]
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    try:
        asyncio.run(run(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
