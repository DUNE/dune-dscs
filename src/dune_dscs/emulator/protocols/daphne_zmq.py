from __future__ import annotations

import asyncio
import itertools
import time
from collections.abc import Iterable
from contextlib import suppress
from typing import Any

import zmq
import zmq.asyncio
from google.protobuf.message import DecodeError

from ..models import DaphneConfig, DaphneModel
from ..models.daphne import DaphneAfeConfig, DaphneChannelConfig
from ._generated import daphneV3_high_level_confs_pb2 as pb


class DaphneZmqFleet:
    """Expose many DAPHNE models through independent ROUTER endpoints."""

    def __init__(
        self,
        models: Iterable[DaphneModel],
        context: zmq.asyncio.Context | None = None,
    ) -> None:
        self.models = tuple(models)
        self.context = context or zmq.asyncio.Context()
        self._owns_context = context is None
        self._listeners: list[_DaphneListener] = []

    @property
    def listener_count(self) -> int:
        return len(self._listeners)

    async def start(self) -> None:
        if self._listeners:
            raise RuntimeError("DAPHNE ZMQ fleet is already started")
        try:
            for model in self.models:
                endpoint = model.identity.endpoint
                if endpoint is None or endpoint.scheme != "tcp":
                    raise ValueError(f"DAPHNE {model.id} requires a tcp endpoint")
                listener = _DaphneListener(model, self.context)
                listener.start()
                self._listeners.append(listener)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        listeners, self._listeners = self._listeners, []
        await asyncio.gather(*(listener.close() for listener in listeners))
        if self._owns_context:
            self.context.destroy(linger=0)


class _DaphneListener:
    _message_sequence = itertools.count(1)

    def __init__(self, model: DaphneModel, context: zmq.asyncio.Context) -> None:
        self.model = model
        self.socket = context.socket(zmq.ROUTER)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.setsockopt(zmq.SNDHWM, 20_000)
        self.socket.setsockopt(zmq.RCVHWM, 20_000)
        self.task: asyncio.Task[None] | None = None

    def start(self) -> None:
        endpoint = self.model.identity.endpoint
        assert endpoint is not None
        self.socket.bind(endpoint.uri)
        self.task = asyncio.create_task(self._serve(), name=f"daphne-zmq:{self.model.id}")

    async def close(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with suppress(asyncio.CancelledError):
                await self.task
            self.task = None
        self.socket.close(linger=0)

    async def _serve(self) -> None:
        while True:
            frames = await self.socket.recv_multipart()
            if len(frames) < 2 or not self.model.available:
                continue
            request = pb.ControlEnvelopeV2()
            try:
                request.ParseFromString(frames[-1])
            except DecodeError:
                continue
            if request.version != 2 or request.dir != pb.DIR_REQUEST:
                continue
            response_payload = await self._dispatch(request.type, request.payload)
            response = pb.ControlEnvelopeV2(
                version=2,
                dir=pb.DIR_RESPONSE,
                type=_response_type(request.type),
                payload=response_payload,
                task_id=request.task_id,
                msg_id=self._next_message_id(),
                correl_id=request.msg_id,
                route=request.route,
                timestamp_ns=time.monotonic_ns(),
            )
            await self.socket.send_multipart([frames[0], response.SerializeToString()])

    async def _dispatch(self, message_type: int, payload: bytes) -> bytes:
        if message_type == pb.MT2_CONFIGURE_FE_REQ:
            request = pb.ConfigureRequest()
            if not _parse(request, payload):
                return pb.ConfigureResponse(success=False, message="Bad ConfigureRequest payload").SerializeToString()
            threshold = request.self_trigger_xcorr or request.self_trigger_threshold
            config = DaphneConfig(
                bias_control=request.biasctrl,
                threshold=threshold,
                channels=tuple(
                    DaphneChannelConfig(item.id, item.trim, item.offset, item.gain)
                    for item in request.channels
                ),
                afes=tuple(
                    DaphneAfeConfig(item.id, item.attenuators, item.v_bias) for item in request.afes
                ),
            )
            try:
                generation = await self.model.configure(config)
                duration_ms = int(self.model.nominal_configure_seconds(config) * 1000)
                return pb.ConfigureResponse(
                    success=True,
                    message=(
                        f"Emulated DAPHNE configuration complete; generation={generation}; "
                        f"nominal_duration_ms={duration_ms}"
                    ),
                ).SerializeToString()
            except Exception as error:
                return pb.ConfigureResponse(success=False, message=str(error)).SerializeToString()

        if message_type == pb.MT2_READ_TRIGGER_COUNTERS_REQ:
            request = pb.ReadTriggerCountersRequest()
            if not _parse(request, payload):
                return pb.ReadTriggerCountersResponse(
                    success=False, message="Bad ReadTriggerCountersRequest payload"
                ).SerializeToString()
            channels = request.channels or range(40)
            response = pb.ReadTriggerCountersResponse(success=True, message="OK")
            for channel_id in channels:
                if not 0 <= channel_id < 40:
                    continue
                state = self.model.channels[channel_id]
                response.snapshots.add(
                    channel=channel_id,
                    threshold=state.threshold,
                    record_count=state.record_count,
                    busy_count=state.busy_count,
                    full_count=state.full_count,
                )
            return response.SerializeToString()

        if message_type == pb.MT2_READ_TEST_REG_REQ:
            return pb.TestRegResponse(value=0xDEADBEEF, message="ok").SerializeToString()

        if message_type == pb.MT2_READ_GENERAL_INFO_REQ:
            request = pb.InfoRequest()
            if not _parse(request, payload):
                return pb.GeneralInfo().SerializeToString()
            return pb.GeneralInfo(**self.model.telemetry).SerializeToString()

        return b""

    @classmethod
    def _next_message_id(cls) -> int:
        return ((time.monotonic_ns() << 16) ^ next(cls._message_sequence)) & ((1 << 63) - 1)


def _response_type(request_type: int) -> int:
    if request_type == 0:
        return pb.MT2_UNSPECIFIED
    return request_type if request_type & 1 else request_type + 1


def _parse(message: Any, payload: bytes) -> bool:
    try:
        message.ParseFromString(payload)
        return True
    except DecodeError:
        return False
