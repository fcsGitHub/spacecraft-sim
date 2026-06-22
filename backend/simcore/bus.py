"""内存发布订阅总线：确定性投递（赋全局 seq + 按主题过滤）。

BusMessage 是内部传输类型（非七参数之一），引擎负责 stamp（补 source/seq）
与延迟缓冲。投递确定性规则见引擎两相调度。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any


@dataclass(frozen=True)
class BusMessage:
    topic: str
    source: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)
    seq: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"topic": self.topic, "source": self.source,
                "data": dict(self.data), "seq": self.seq}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> "BusMessage":
        return cls(topic=str(d["topic"]), source=str(d.get("source", "")),
                   data=dict(d.get("data") or {}), seq=int(d.get("seq", 0)))


class MessageBus:
    """全局序号发放与主题过滤；缓冲由引擎持有以保证克隆可恢复。"""

    def __init__(self) -> None:
        self._seq = 0

    def stamp(self, messages: tuple[BusMessage, ...], source: str) -> tuple[BusMessage, ...]:
        out: list[BusMessage] = []
        for m in messages:
            out.append(replace(m, source=source or m.source, seq=self._seq))
            self._seq += 1
        return tuple(out)

    @staticmethod
    def filter_for(messages: tuple[BusMessage, ...], topics: set[str]) -> tuple[BusMessage, ...]:
        if not topics:
            return ()
        return tuple(m for m in messages if m.topic in topics)
