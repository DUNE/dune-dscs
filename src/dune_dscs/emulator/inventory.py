from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Endpoint:
    scheme: str
    host: str
    port: int

    def __post_init__(self) -> None:
        if not self.scheme:
            raise ValueError("endpoint scheme is required")
        if not self.host:
            raise ValueError("endpoint host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError(f"endpoint port out of range: {self.port}")

    @property
    def uri(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"


@dataclass(frozen=True, slots=True)
class DeviceIdentity:
    id: str
    kind: str
    endpoint: Endpoint | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)
