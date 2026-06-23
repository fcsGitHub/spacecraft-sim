# backend/simcore/models/adjud_perception_full.py
"""全域实时感知裁决（type 1）：双方完全实时感知对方位置速度。

读本步全部实体真值，按阵营产出各阵营对非己方实体的实时位置速度（age_s=0）。
仅出帧用于显示，不回传总线。
"""

from __future__ import annotations

from typing import Any

from simcore.model import AdjudicationModel, Array6, SimContext
from simcore.params import ParamMROutput, ParamRTInput, ParamRTOutput, StepResult
from simcore.registry import register_model


@register_model
class FullPerceptionAdjudication(AdjudicationModel):
    model_type = "adjud.perception_full"
    display_name = "全域实时感知裁决"
    category = "adjudication"
    description = "各阵营完全实时感知所有非己方实体的位置速度。"

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = rt_in.env.get("sim_time", ctx.sim_time)
        states = rt_in.env.get("entities", {})
        factions = {st.get("faction") for st in states.values() if st.get("faction")}
        perception: dict[str, dict[str, dict[str, Any]]] = {}
        for f in factions:
            bucket: dict[str, dict[str, Any]] = {}
            for eid, st in states.items():
                if st.get("faction") == f or not st.get("pos_km"):
                    continue
                bucket[eid] = {
                    "pos_km": list(st["pos_km"]),
                    "vel_kmps": list(st.get("vel_kmps") or []),
                    "source": "realtime",
                    "age_s": 0.0,
                }
            if bucket:
                perception[f] = bucket
        return StepResult(rt_output=ParamRTOutput(data={"perception": perception}),
                          mr_output=ParamMROutput(time=sim_t, state={}))
