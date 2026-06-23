# backend/simcore/models/adjud_perception_delay.py
"""延时感知裁决（type 2）：各阵营获取非己方实体 delay_s 前的位置速度。

内部环形缓冲保存最近若干步的实体位置速度快照；每步取 t-delay_s 处快照
（不足则取最早可用），按阵营产出延时感知（source=delayed, age_s=实际滞后）。
缓冲纳入 MR，保证预推演克隆/回放断点逐位复现。仅出帧用于显示。
"""

from __future__ import annotations

import math
from typing import Any

from simcore.model import AdjudicationModel, Array6, SimContext
from simcore.params import (
    ParamAttribute,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model


@register_model
class DelayedPerceptionAdjudication(AdjudicationModel):
    model_type = "adjud.perception_delay"
    display_name = "延时感知裁决"
    category = "adjudication"
    description = "各阵营获取非己方实体若干时长前的位置速度，可自行外推。"

    attribute_schema = {
        "delay_s": {"type": "number", "unit": "s", "default": 30.0, "desc": "感知滞后时长"},
    }

    def __init__(self) -> None:
        super().__init__()
        self.delay_s = 30.0
        self._buf: list[dict[str, Any]] = []   # [{"t": float, "states": {eid: {pos_km, vel_kmps, faction}}}]

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self.delay_s = float(data["delay_s"])
        self._buf = []
        return 0

    def _capacity(self, step: float) -> int:
        s = step if step > 0 else 1.0
        return int(math.ceil(self.delay_s / s)) + 2

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = float(rt_in.env.get("sim_time", ctx.sim_time))
        states = rt_in.env.get("entities", {})
        snap = {eid: {"pos_km": list(st["pos_km"]),
                      "vel_kmps": list(st.get("vel_kmps") or []),
                      "faction": st.get("faction", "")}
                for eid, st in states.items() if st.get("pos_km")}
        self._buf.append({"t": sim_t, "states": snap})
        cap = self._capacity(step)
        if len(self._buf) > cap:
            del self._buf[:len(self._buf) - cap]

        target_t = sim_t - self.delay_s
        chosen = self._buf[0]
        for rec in self._buf:
            if rec["t"] <= target_t + 1e-9:
                chosen = rec
            else:
                break
        age = round(sim_t - chosen["t"], 3)
        factions = {s.get("faction") for s in chosen["states"].values() if s.get("faction")}
        perception: dict[str, dict[str, dict[str, Any]]] = {}
        for f in factions:
            bucket: dict[str, dict[str, Any]] = {}
            for eid, s in chosen["states"].items():
                if s.get("faction") == f:
                    continue
                bucket[eid] = {"pos_km": list(s["pos_km"]),
                               "vel_kmps": list(s.get("vel_kmps") or []),
                               "source": "delayed", "age_s": age}
            if bucket:
                perception[f] = bucket
        return StepResult(rt_output=ParamRTOutput(data={"perception": perception}),
                          mr_output=ParamMROutput(time=sim_t, state={"buf": list(self._buf)}))

    def sim_restore(self, mr: ParamMROutput) -> int:
        raw = dict(mr.state).get("buf") or []
        self._buf = [{"t": float(r["t"]), "states": dict(r["states"])} for r in raw]
        return 0
