# backend/simcore/models/sensor_perception.py
"""感知载荷原子模型：开机时发布感知扫描，由星上感知裁决判定可感知目标。

指控指令：sensor_ctrl {act: 开机/关机}
发布主题：perception.scan（携带作用距离/目标阵营供裁决使用）
订阅主题：perception.result（上一步裁决回传本观测方的已感知目标）
实时输出：perc_state、sensed_count、sensed_ids
"""

from __future__ import annotations

from simcore.bus import BusMessage
from simcore.model import Array6, AtomicModel, SimContext
from simcore.params import (
    ParamAttribute,
    ParamCtrInput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model

PERC_STATES = ("待机", "开机", "关闭")


@register_model
class PerceptionSensorModel(AtomicModel):
    model_type = "sensor.perception"
    display_name = "感知载荷"
    category = "sensor"
    description = "在作用距离内感知非己方目标位置速度，可感知性由星上感知裁决判定。"

    subscribes = ("perception.result",)
    publishes = ("perception.scan",)

    attribute_schema = {
        "max_range_km": {"type": "number", "unit": "km", "default": 3000.0, "desc": "最大感知距离"},
        "state": {"type": "select", "options": list(PERC_STATES), "default": "开机", "desc": "初始状态"},
        "target_factions": {"type": "string", "default": "", "desc": "目标阵营（逗号分隔，空=所有非己方）"},
    }
    ctr_commands = {
        "sensor_ctrl": {
            "desc": "感知载荷控制",
            "params": {"act": {"type": "select", "options": ["开机", "关机"], "desc": "动作"}},
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._max_range_km = 3000.0
        self._target_factions = ""
        self._state = "开机"
        self._sensed_ids: list[str] = []

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self._max_range_km = float(data["max_range_km"])
        self._target_factions = str(data.get("target_factions") or "")
        state = str(data.get("state") or "开机")
        self._state = state if state in PERC_STATES else "开机"
        self._sensed_ids = []
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        if ctr_in.name == "sensor_ctrl":
            act = str(ctr_in.params.get("act") or "")
            if act == "开机":
                self._state = "开机"
            elif act == "关机":
                self._state = "关闭"
            else:
                return 1
            return 0
        return 0

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = ctx.sim_time + step
        messages: list[BusMessage] = []
        for m in rt_in.messages:
            if m.topic == "perception.result" and str(m.data.get("observer")) == ctx.entity_id:
                sensed = m.data.get("sensed") or []
                self._sensed_ids = [str(s.get("id")) for s in sensed if s.get("id")]
        if self._state == "开机":
            messages.append(BusMessage(topic="perception.scan", data={
                "observer": ctx.entity_id,
                "faction": str(rt_in.upstream.get("faction") or ""),
                "max_range_km": self._max_range_km,
                "target_factions": self._target_factions,
            }))
        rt_output = ParamRTOutput(data={
            "perc_state": self._state,
            "sensed_count": len(self._sensed_ids),
            "sensed_ids": list(self._sensed_ids),
        })
        mr = ParamMROutput(time=sim_t, state={"state": self._state, "sensed_ids": list(self._sensed_ids)})
        return StepResult(rt_output=rt_output, messages=tuple(messages), mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        s = dict(mr.state)
        st = str(s.get("state", "开机"))
        self._state = st if st in PERC_STATES else "开机"
        self._sensed_ids = [str(x) for x in (s.get("sensed_ids") or [])]
        return 0
