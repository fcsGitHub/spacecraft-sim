"""相机/光学传感器原子模型：发起拍照请求，由空间拍照裁决判定成败。

指控指令：take_photo {target}、standby
发布主题：camera.photo_request（携带相机参数供裁决使用）
订阅主题：camera.photo_result（上一拍裁决回传，更新成像计数）
实时输出：cam_state、shots、last_result
"""

from __future__ import annotations

from simcore.bus import BusMessage
from simcore.model import Array6, AtomicModel, SimContext
from simcore.params import (
    ParamAttribute,
    ParamCtrInput,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model

POINT_MODES = ("跟踪目标", "对地固定")


@register_model
class CameraModel(AtomicModel):
    model_type = "sensor.camera"
    display_name = "光学相机"
    category = "sensor"
    description = "发起空间拍照请求，成败由空间拍照裁决模型判定。"

    subscribes = ("camera.photo_result",)
    publishes = ("camera.photo_request",)

    attribute_schema = {
        "fov_deg": {"type": "number", "unit": "°", "default": 5.0, "desc": "视场全角"},
        "max_range_km": {"type": "number", "unit": "km", "default": 2000.0, "desc": "最大作用距离"},
        "sun_exclusion_deg": {"type": "number", "unit": "°", "default": 30.0, "desc": "防眩光最小日-视线夹角"},
        "ifov_urad": {"type": "number", "unit": "µrad", "default": 50.0, "desc": "每像素瞬时视场"},
        "gsd_threshold_m": {"type": "number", "unit": "m", "default": 5.0, "desc": "成像质量门限(GSD)"},
        "point_mode": {"type": "select", "options": list(POINT_MODES), "default": "跟踪目标", "desc": "指向模式"},
    }
    ctr_commands = {
        "take_photo": {"desc": "发起拍照", "params": {"target": {"type": "string", "desc": "目标实体ID"}}},
        "standby": {"desc": "相机待机", "params": {}},
    }

    def __init__(self) -> None:
        super().__init__()
        self._params: dict[str, float | str] = {}
        self._pending_target: str | None = None
        self._request_id = 0
        self._shots = 0
        self._last_result = "无"
        self._cam_state = "待机"

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self._params = {
            "fov_deg": float(data["fov_deg"]),
            "max_range_km": float(data["max_range_km"]),
            "sun_exclusion_deg": float(data["sun_exclusion_deg"]),
            "ifov_urad": float(data["ifov_urad"]),
            "gsd_threshold_m": float(data["gsd_threshold_m"]),
            "point_mode": str(data["point_mode"]),
        }
        self._pending_target = None
        self._request_id = 0
        self._shots = 0
        self._last_result = "无"
        self._cam_state = "待机"
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        if ctr_in.name == "take_photo":
            target = str(ctr_in.params.get("target") or "")
            if not target:
                return 1
            self._pending_target = target
            self._cam_state = "拍照"
            return 0
        if ctr_in.name == "standby":
            self._cam_state = "待机"
            return 0
        return 0

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = ctx.sim_time + step
        events: list[ParamKeyOutput] = []
        messages: list[BusMessage] = []

        # 1) 消费上一拍裁决回传
        for m in rt_in.messages:
            if m.topic == "camera.photo_result":
                success = bool(m.data.get("success"))
                self._last_result = "成功" if success else "失败"
                if success:
                    self._shots += 1
                events.append(ParamKeyOutput(
                    time=sim_t, entity_id=ctx.entity_id, source=ctx.component,
                    level="info" if success else "warning", event="载荷",
                    message=f"{ctx.entity_id} 拍照{self._last_result}"
                            + (f"（质量 {float(m.data.get('quality', 0)):.2f}）" if success
                               else f"：{m.data.get('reason', '')}"),
                    data=dict(m.data),
                ))

        # 2) 发起本拍拍照请求
        if self._pending_target is not None:
            self._request_id += 1
            req_target = self._pending_target
            self._pending_target = None
            messages.append(BusMessage(topic="camera.photo_request", data={
                "photographer": ctx.entity_id,
                "target": req_target,
                "request_id": self._request_id,
                "fov_deg": self._params["fov_deg"],
                "max_range_km": self._params["max_range_km"],
                "sun_exclusion_deg": self._params["sun_exclusion_deg"],
                "ifov_urad": self._params["ifov_urad"],
                "gsd_threshold_m": self._params["gsd_threshold_m"],
                "point_mode": self._params["point_mode"],
            }))
            events.append(ParamKeyOutput(
                time=sim_t, entity_id=ctx.entity_id, source=ctx.component,
                level="info", event="载荷",
                message=f"{ctx.entity_id} 对 {req_target} 发起拍照",
                data={"request_id": self._request_id, "target": req_target},
            ))

        rt_output = ParamRTOutput(data={
            "cam_state": self._cam_state,
            "shots": self._shots,
            "last_result": self._last_result,
        })
        mr = ParamMROutput(time=sim_t, state={
            "request_id": self._request_id, "shots": self._shots,
            "last_result": self._last_result, "cam_state": self._cam_state,
        })
        return StepResult(rt_output=rt_output, key_outputs=tuple(events),
                          messages=tuple(messages), mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        s = dict(mr.state)
        self._request_id = int(s.get("request_id", 0))
        self._shots = int(s.get("shots", 0))
        self._last_result = str(s.get("last_result", "无"))
        self._cam_state = str(s.get("cam_state", "待机"))
        return 0
