"""空间拍照裁决模型：几何 → 光照 → 成像质量 三段评判。

订阅 camera.photo_request；从本拍实体态读拍照星/目标星 pos_km，
评判成败与质量分，产出裁决事件并发布 camera.photo_result（延迟一拍回传相机）。
"""

from __future__ import annotations

import math
from typing import Any

from simcore.bus import BusMessage
from simcore.model import AdjudicationModel, Array6, SimContext
from simcore.params import (
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model
from simcore.sun import MEAN_EARTH_R_KM, is_sunlit

Vec3 = tuple[float, float, float]


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _norm(v: Vec3) -> float:
    return math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2])


def _dot(a: Vec3, b: Vec3) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _earth_occluded(r_cam: Vec3, r_tgt: Vec3, r_e: float) -> bool:
    """线段 cam→tgt 与地球球体相交（最近点落在段内且 |p| < R_E）。"""
    los = _sub(r_tgt, r_cam)
    ll = _dot(los, los)
    if ll <= 0:
        return False
    s = max(0.0, min(1.0, -_dot(r_cam, los) / ll))
    p = (r_cam[0] + s * los[0], r_cam[1] + s * los[1], r_cam[2] + s * los[2])
    return _norm(p) < r_e


@register_model
class PhotoAdjudication(AdjudicationModel):
    model_type = "adjud.photo"
    display_name = "空间拍照裁决"
    category = "adjudication"
    description = "对拍照请求按几何/光照/成像质量评判成败与质量分。"

    subscribes = ("camera.photo_request",)
    publishes = ("camera.photo_result",)

    def __init__(self) -> None:
        super().__init__()
        self._count = 0

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        sim_t = rt_in.env.get("sim_time", ctx.sim_time)
        states = rt_in.env.get("entities", {})
        raw_sun = rt_in.env.get("sun_eci", (1.0, 0.0, 0.0))
        sun_hat: Vec3 = (float(raw_sun[0]), float(raw_sun[1]), float(raw_sun[2]))
        events: list[ParamKeyOutput] = []
        messages: list[BusMessage] = []

        for msg in rt_in.messages:
            if msg.topic != "camera.photo_request":
                continue
            self._count += 1
            verdict = self._judge(msg.data, states, sun_hat)
            verdict["request_id"] = msg.data.get("request_id")
            success = verdict["success"]
            events.append(ParamKeyOutput(
                time=sim_t, entity_id=str(msg.data.get("photographer", "")),
                source="adjud.photo", level="info" if success else "warning",
                event="裁决",
                message=(f"{msg.data.get('photographer')} 拍 {msg.data.get('target')} "
                         + ("成功，质量 %.2f" % verdict["quality"] if success
                            else f"失败：{verdict['reason']}")),
                data=dict(verdict),
            ))
            messages.append(BusMessage(topic="camera.photo_result", data=dict(verdict)))

        return StepResult(rt_output=ParamRTOutput(), key_outputs=tuple(events),
                          messages=tuple(messages),
                          mr_output=ParamMROutput(time=sim_t, state={"count": self._count}))

    def _judge(self, req: dict[str, Any], states: dict[str, Any], sun_hat: Vec3) -> dict[str, Any]:
        out: dict[str, Any] = {"success": False, "quality": 0.0, "reason": "",
                               "gsd_m": 0.0, "range_km": 0.0}
        cam_s = states.get(str(req.get("photographer")))
        tgt_s = states.get(str(req.get("target")))
        if not cam_s or not tgt_s or not cam_s.get("pos_km") or not tgt_s.get("pos_km"):
            out["reason"] = "目标不可见"
            return out
        cp, tp = cam_s["pos_km"], tgt_s["pos_km"]
        r_cam: Vec3 = (float(cp[0]), float(cp[1]), float(cp[2]))
        r_tgt: Vec3 = (float(tp[0]), float(tp[1]), float(tp[2]))
        los = _sub(r_tgt, r_cam)
        rng = _norm(los)
        out["range_km"] = round(rng, 3)
        if rng <= 1e-6:
            out["reason"] = "目标不可见"
            return out
        los_hat = (los[0] / rng, los[1] / rng, los[2] / rng)

        # --- 几何 ---
        if rng > float(req["max_range_km"]):
            out["reason"] = "超出作用距离"
            return out
        if str(req.get("point_mode")) == "对地固定":
            rc = _norm(r_cam)
            boresight = (-r_cam[0] / rc, -r_cam[1] / rc, -r_cam[2] / rc)
            ang = math.degrees(math.acos(max(-1.0, min(1.0, _dot(boresight, los_hat)))))
            if ang > float(req["fov_deg"]) / 2.0:
                out["reason"] = "目标在视场外"
                return out
        if _earth_occluded(r_cam, r_tgt, MEAN_EARTH_R_KM):
            out["reason"] = "地球遮挡"
            return out

        # --- 光照 ---
        if not is_sunlit(r_tgt, sun_hat):
            out["reason"] = "目标未受照"
            return out
        glare = math.degrees(math.acos(max(-1.0, min(1.0, _dot(los_hat, sun_hat)))))
        if glare < float(req["sun_exclusion_deg"]):
            out["reason"] = "太阳眩光"
            return out

        # --- 成像质量 ---
        gsd_m = rng * float(req["ifov_urad"]) * 1e-3
        out["gsd_m"] = round(gsd_m, 3)
        if gsd_m > float(req["gsd_threshold_m"]):
            out["reason"] = "分辨率不足"
            return out
        out["success"] = True
        out["quality"] = round(max(0.0, min(1.0, float(req["gsd_threshold_m"]) / gsd_m)), 4)
        return out

    def sim_restore(self, mr: ParamMROutput) -> int:
        self._count = int(dict(mr.state).get("count", 0))
        return 0
