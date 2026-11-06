"""Run one PDU, DAPHNE or WIB protocol emulator."""

import argparse
import asyncio

import zmq
import zmq.asyncio
from google.protobuf.message import DecodeError


async def run(args):
    if args.kind == "pdu":
        from .pdu import PduAgent
        agent = PduAgent(args.host, args.port, args.outlets, args.community)
        try:
            await agent.start()
            print(f"PDU listening on {args.host}:{args.port}", flush=True)
            await asyncio.Event().wait()
        finally:
            await agent.close()
        return

    from .daphne import Daphne
    from .wib import Wib
    device = Daphne() if args.kind == "daphne" else Wib()
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
                reply = device.reply(frames[-1])
                if reply is not None:
                    await socket.send_multipart([*frames[:-1], reply])
            else:
                try:
                    reply = await device.reply(frames[-1])
                except (DecodeError, ValueError):
                    reply = b""
                await socket.send(reply)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("pdu", "daphne", "wib"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int)
    parser.add_argument("--outlets", type=int, default=10)
    parser.add_argument("--community", default="private")
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
