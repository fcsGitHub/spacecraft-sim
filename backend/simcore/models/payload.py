"""通用载荷模型：载荷状态机 + 任务事件记录。

指控指令：payload_ctrl {act: 开机/关机/单次成像/持续侦收}、log {desc}
导调指令：fault {desc} 载荷故障
实时输出：payload_type、payload_state、power_w
"""

from __future__ import annotations

from simcore.model import Array6, AtomicModel, SimContext
from simcore.params import (
    ParamAttribute,
    ParamCtrInput,
    ParamDirInput,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model

PAYLOAD_STATES = ("待机", "开机", "关闭", "故障")


@register_model
class GenericPayloadModel(AtomicModel):
    model_type = "payload.generic"
    display_name = "通用载荷"
    category = "payload"
    description = "载荷开关机/成像/侦收状态机，关键动作产生事件记录。"

    attribute_schema = {
        "payload_type": {"type": "string", "default": "光学成像", "desc": "载荷类型"},
        "state": {
            "type": "select", "options": ["待机", "开机", "关闭"],
            "default": "待机", "desc": "初始状态",
        },
        "power_w": {"type": "number", "unit": "W", "default": 320.0, "desc": "额定功率"},
    }
    ctr_commands = {
        "payload_ctrl": {
            "desc": "载荷控制",
            "params": {
                "act": {
                    "type": "select",
                    "options": ["开机", "关机", "单次成像", "持续侦收"],
                    "desc": "动作",
                },
            },
        },
        "log": {"desc": "记录事件（无状态影响）", "params": {"desc": {"type": "string", "desc": "内容"}}},
    }
    dir_commands = {
        "fault": {"desc": "载荷故障", "params": {"desc": {"type": "string", "desc": "故障说明"}}},
    }

    def __init__(self) -> None:
        super().__init__()
        self._type = "光学成像"
        self._state = "待机"
        self._power_w = 320.0
        self._pending_events: list[tuple[str, str]] = []  # (event_type, message)

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self._type = str(data.get("payload_type") or "未知")
        state = str(data.get("state") or "待机")
        self._state = state if state in PAYLOAD_STATES else "待机"
        self._power_w = float(data.get("power_w") or 0)
        self._pending_events = []
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        if ctr_in.name == "payload_ctrl":
            if self._state == "故障":
                return 2
            act = str(ctr_in.params.get("act") or "")
            if act == "开机":
                self._state = "开机"
            elif act == "关机":
                self._state = "关闭"
            elif act == "单次成像":
                if self._state != "开机":
                    self._state = "开机"
                self._pending_events.append(("载荷", f"{ctr_in.entity_id} {self._type} 完成单次成像"))
            elif act == "持续侦收":
                self._state = "开机"
            else:
                return 1
            return 0
        if ctr_in.name == "log":
            desc = str(ctr_in.params.get("desc") or "")
            if desc:
                self._pending_events.append(("系统", f"{ctr_in.entity_id} {desc}"))
            return 0
        return 0

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        if dir_in.name == "fault":
            self._state = "故障"
            self._pending_events.append(
                ("系统", f"{dir_in.entity_id} 载荷故障: {dir_in.params.get('desc') or '导调注入'}")
            )
        return 0

    def sim_advance(
        self, ctx: SimContext, bjt: Array6, utc: Array6, step: float, rt_in: ParamRTInput
    ) -> StepResult:
        sim_t = ctx.sim_time + step
        events = tuple(
            ParamKeyOutput(
                time=sim_t, entity_id=ctx.entity_id, source=ctx.component,
                level="info" if ev_type == "载荷" else "warning",
                event=ev_type, message=message,
            )
            for ev_type, message in self._pending_events
        )
        self._pending_events = []
        rt_output = ParamRTOutput(data={
            "payload_type": self._type,
            "payload_state": self._state,
            "power_w": self._power_w if self._state == "开机" else 0.0,
        })
        mr = ParamMROutput(time=sim_t, state={"state": self._state})
        return StepResult(rt_output=rt_output, key_outputs=events, mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        state = str(dict(mr.state).get("state", self._state))
        if state in PAYLOAD_STATES:
            self._state = state
        return 0
