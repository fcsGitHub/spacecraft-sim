# backend/simcore/models/adjud_perception_onboard.py
"""星上感知裁决（type 3）：判定非己方目标是否被感知载荷感知。

订阅 perception.scan；对每条扫描在作用距离内（仅距离判定）找非己方目标，
感知则产出实时位置速度（source=onboard），并发布 perception.result 回传观测方
（延迟一拍达观测方载荷）。阵营级融合：同阵营任一载荷感知到即该阵营感知到。
"""

from __future__ import annotations

import math
from typing import Any

from simcore.bus import BusMessage
from simcore.model import AdjudicationModel, Array6, SimContext
from simcore.params import ParamMROutput, ParamRTInput, ParamRTOutput, StepResult
from simcore.registry import register_model


@register_model
class OnboardPerceptionAdjudication(AdjudicationModel):
    model_type = "adjud.perception_onboard"
    display_name = "星上感知裁决"
    category = "adjudication"
    description = "判定非己方目标是否被感知载荷在作用距离内感知（仅距离判定）。"

    subscribes = ("perception.scan",)
    publishes = ("perception.result",)

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = rt_in.env.get("sim_time", ctx.sim_time)
        states = rt_in.env.get("entities", {})
        perception: dict[str, dict[str, dict[str, Any]]] = {}
        per_observer: dict[str, list[dict[str, Any]]] = {}

        for msg in rt_in.messages:
            if msg.topic != "perception.scan":
                continue
            observer = str(msg.data.get("observer") or "")
            faction = str(msg.data.get("faction") or "")
            rng = float(msg.data.get("max_range_km") or 0.0)
            tf_raw = str(msg.data.get("target_factions") or "")
            target_factions = {x.strip() for x in tf_raw.split(",") if x.strip()}
            obs_state = states.get(observer)
            if not obs_state or not obs_state.get("pos_km") or rng <= 0:
                continue
            op = obs_state["pos_km"]
            rng_sq = rng * rng
            for tid, st in states.items():
                tf = st.get("faction", "")
                if tf == faction:                       # 己方不算
                    continue
                if target_factions and tf not in target_factions:
                    continue
                tp = st.get("pos_km")
                if not tp:
                    continue
                dx, dy, dz = op[0] - tp[0], op[1] - tp[1], op[2] - tp[2]
                d_sq = dx * dx + dy * dy + dz * dz
                if d_sq > rng_sq:
                    continue
                dist = round(math.sqrt(d_sq), 3)
                bucket = perception.setdefault(faction, {})
                entry = bucket.get(tid)
                if entry is None:
                    bucket[tid] = {"pos_km": list(tp), "vel_kmps": list(st.get("vel_kmps") or []),
                                   "source": "onboard", "age_s": 0.0, "observers": [observer]}
                elif observer not in entry["observers"]:
                    entry["observers"].append(observer)
                per_observer.setdefault(observer, []).append(
                    {"id": tid, "faction": tf, "pos_km": list(tp),
                     "vel_kmps": list(st.get("vel_kmps") or []), "range_km": dist})

        messages = [BusMessage(topic="perception.result",
                               data={"observer": obs, "sensed": sensed})
                    for obs, sensed in per_observer.items()]
        return StepResult(rt_output=ParamRTOutput(data={"perception": perception}),
                          messages=tuple(messages),
                          mr_output=ParamMROutput(time=sim_t, state={}))
