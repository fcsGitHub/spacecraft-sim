"""接近预警裁决模型（由引擎原 _check_proximity 迁移而来）。

中立、全局；读本拍全部实体 pos_km，对星对距离低于门限产生一次预警，
迟滞防止事件洪泛（已预警星对在分离前不重复报警）。
"""

from __future__ import annotations

from simcore.model import AdjudicationModel, Array6, SimContext
from simcore.params import (
    ParamAttribute,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model


@register_model
class ProximityAdjudication(AdjudicationModel):
    model_type = "adjud.proximity"
    display_name = "接近预警裁决"
    category = "adjudication"
    description = "星对距离低于门限时产生预警（带迟滞）。"

    attribute_schema = {
        "threshold_km": {"type": "number", "unit": "km", "default": 100.0, "desc": "预警门限距离"},
    }

    def __init__(self) -> None:
        super().__init__()
        self.threshold_km = 100.0          # 公开属性：供引擎 alert_threshold_km 代理读写
        self._seen: set[str] = set()

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self.threshold_km = float(data["threshold_km"])
        self._seen = set()
        return 0

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        states = rt_in.env.get("entities", {})
        sim_t = rt_in.env.get("sim_time", ctx.sim_time)
        ids = list(states.keys())
        thr_sq = self.threshold_km * self.threshold_km
        events: list[ParamKeyOutput] = []
        active: set[str] = set()
        for i in range(len(ids)):
            pos_i = states[ids[i]].get("pos_km")
            if not pos_i:
                continue
            for j in range(i + 1, len(ids)):
                pos_j = states[ids[j]].get("pos_km")
                if not pos_j:
                    continue
                dx = pos_i[0] - pos_j[0]
                dy = pos_i[1] - pos_j[1]
                dz = pos_i[2] - pos_j[2]
                dist_sq = dx * dx + dy * dy + dz * dz
                if dist_sq >= thr_sq:
                    continue
                pair = f"{ids[i]}|{ids[j]}"
                active.add(pair)
                if pair not in self._seen:
                    self._seen.add(pair)
                    dist = dist_sq ** 0.5
                    events.append(ParamKeyOutput(
                        time=sim_t, entity_id=ids[i], source="proximity",
                        level="warning", event="预警",
                        message=f"{ids[i]} ↔ {ids[j]} 接近 {dist:.0f} km",
                        data={"pair": [ids[i], ids[j]], "dist_km": round(dist, 2)},
                    ))
        # 已分离的星对解除迟滞，允许再次接近时重新报警
        self._seen &= active
        return StepResult(rt_output=ParamRTOutput(),
                          key_outputs=tuple(events),
                          mr_output=ParamMROutput(time=sim_t, state={"seen": sorted(self._seen)}))

    def sim_restore(self, mr: ParamMROutput) -> int:
        self._seen = set(dict(mr.state).get("seen", []))
        return 0
