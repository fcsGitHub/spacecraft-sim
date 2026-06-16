"""推进/机动模型：有限时长点火 + 简化编队保持控制器。

指控指令：
    maneuver {dv_mps, dir: 切向/法向/径向}  按 burn_duration_s 分摊为推力加速度
    formation_keep {ref_id, dist_km}        视线方向 P 控制（示例控制器，供研究算法替换）
导调指令：
    fault {desc}                            推进系统失效（不再响应机动）

实时输出：thrust_accel_mps2 [ax,ay,az] (ECI, m/s²)、fuel_pct、mass_kg、thrusting
本组件须置于 orbit 组件之前（推力经 upstream 传递）。
"""

from __future__ import annotations

import math
from typing import Any

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

# 燃料消耗系数（%/(m/s)）：与前端遥测显示约定一致的简化模型
FUEL_PCT_PER_MPS = 0.45
# 编队保持控制参数
FORMATION_GAIN = 2e-4       # m/s² per km 误差
FORMATION_MAX_ACCEL = 0.02  # m/s²

Vec3 = tuple[float, float, float]


def _unit(v: Vec3) -> Vec3 | None:
    mag = math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2)
    if mag < 1e-9:
        return None
    return (v[0] / mag, v[1] / mag, v[2] / mag)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


@register_model
class ThrusterModel(AtomicModel):
    model_type = "prop.thruster"
    display_name = "推进机动"
    category = "propulsion"
    description = "有限点火机动 + 简化编队保持，输出推力加速度与燃料余量。"

    attribute_schema = {
        "mass_kg": {"type": "number", "unit": "kg", "default": 1000.0, "desc": "整星质量"},
        "fuel_pct": {"type": "number", "unit": "%", "default": 100.0, "desc": "燃料余量"},
        "isp_s": {"type": "number", "unit": "s", "default": 300.0, "desc": "比冲（预留）"},
        "burn_duration_s": {"type": "number", "unit": "s", "default": 10.0, "desc": "单次点火时长"},
    }
    ctr_commands = {
        "maneuver": {
            "desc": "轨道机动",
            "params": {
                "dv_mps": {"type": "number", "unit": "m/s", "desc": "速度增量"},
                "dir": {"type": "select", "options": ["切向", "法向", "径向"], "desc": "机动方向"},
            },
        },
        "formation_keep": {
            "desc": "编队保持（示例控制器）",
            "params": {
                "ref_id": {"type": "string", "desc": "参考星编号"},
                "dist_km": {"type": "number", "unit": "km", "desc": "保持距离"},
            },
        },
    }
    dir_commands = {
        "fault": {"desc": "推进系统失效", "params": {"desc": {"type": "string", "desc": "故障说明"}}},
    }

    def __init__(self) -> None:
        super().__init__()
        self._mass_kg = 1000.0
        self._fuel_pct = 100.0
        self._burn_duration_s = 10.0
        self._burns: list[dict[str, Any]] = []   # {dv_left, dir, dv_total}
        self._formation: dict[str, Any] | None = None
        self._failed = False

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        self._mass_kg = float(data["mass_kg"])
        self._fuel_pct = float(data["fuel_pct"])
        self._burn_duration_s = max(1.0, float(data["burn_duration_s"]))
        self._burns = []
        self._formation = None
        self._failed = False
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        if self._failed:
            return 2
        if ctr_in.name == "maneuver":
            dv = float(ctr_in.params.get("dv_mps") or 0)
            if dv <= 0:
                return 1
            direction = str(ctr_in.params.get("dir") or "切向")
            self._burns.append({"dv_left": dv, "dv_total": dv, "dir": direction})
            return 0
        if ctr_in.name == "formation_keep":
            ref = str(ctr_in.params.get("ref_id") or "")
            if not ref:
                return 1
            self._formation = {"ref_id": ref, "dist_km": float(ctr_in.params.get("dist_km") or 50)}
            return 0
        return 0

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        if dir_in.name == "fault":
            self._failed = True
            self._burns = []
            self._formation = None
        return 0

    def _direction_vector(self, direction: str, pos: Vec3, vel: Vec3) -> Vec3 | None:
        if direction == "切向":
            return _unit(vel)
        if direction == "径向":
            return _unit(pos)
        if direction == "法向":
            return _unit(_cross(pos, vel) or (0, 0, 1))
        return None

    def sim_advance(
        self, ctx: SimContext, bjt: Array6, utc: Array6, step: float, rt_in: ParamRTInput
    ) -> StepResult:
        accel: Vec3 = (0.0, 0.0, 0.0)
        events: list[ParamKeyOutput] = []
        sim_t = ctx.sim_time + step

        # 自身上一步状态（环境快照），t=0 首帧无环境时不产生推力
        own = (rt_in.env.get("entities") or {}).get(ctx.entity_id) or {}
        pos_km = own.get("pos_km")
        vel_kmps = own.get("vel_kmps")

        if step > 0 and not self._failed and self._fuel_pct > 0 and pos_km and vel_kmps:
            pos = (pos_km[0] * 1000, pos_km[1] * 1000, pos_km[2] * 1000)
            vel = (vel_kmps[0] * 1000, vel_kmps[1] * 1000, vel_kmps[2] * 1000)
            if self._burns:
                burn = self._burns[0]
                unit = self._direction_vector(str(burn["dir"]), pos, vel)
                if unit is None:
                    self._burns.pop(0)
                else:
                    rate = float(burn["dv_total"]) / self._burn_duration_s
                    dv_step = min(rate * step, float(burn["dv_left"]))
                    accel = (unit[0] * dv_step / step, unit[1] * dv_step / step, unit[2] * dv_step / step)
                    burn["dv_left"] = float(burn["dv_left"]) - dv_step
                    self._fuel_pct = max(0.0, self._fuel_pct - dv_step * FUEL_PCT_PER_MPS)
                    if burn["dv_left"] <= 1e-9:
                        self._burns.pop(0)
                        events.append(ParamKeyOutput(
                            time=sim_t, entity_id=ctx.entity_id, source=ctx.component,
                            level="info", event="机动",
                            message=f"{ctx.entity_id} 点火完成 Δv={burn['dv_total']} m/s {burn['dir']}",
                            data={"dv_mps": burn["dv_total"], "dir": burn["dir"]},
                        ))
            elif self._formation:
                ref_state = (rt_in.env.get("entities") or {}).get(self._formation["ref_id"]) or {}
                ref_pos = ref_state.get("pos_km")
                if ref_pos:
                    rel = (ref_pos[0] - pos_km[0], ref_pos[1] - pos_km[1], ref_pos[2] - pos_km[2])
                    dist_km = math.sqrt(rel[0] ** 2 + rel[1] ** 2 + rel[2] ** 2)
                    error_km = dist_km - float(self._formation["dist_km"])
                    unit = _unit(rel)
                    if unit and abs(error_km) > 0.5:
                        mag = max(-FORMATION_MAX_ACCEL, min(FORMATION_MAX_ACCEL, FORMATION_GAIN * error_km))
                        accel = (unit[0] * mag, unit[1] * mag, unit[2] * mag)
                        self._fuel_pct = max(0.0, self._fuel_pct - abs(mag) * step * FUEL_PCT_PER_MPS)

        # 怠速损耗（姿控微推等）
        if step > 0:
            self._fuel_pct = max(0.0, self._fuel_pct - step * 4e-5)

        thrusting = accel != (0.0, 0.0, 0.0)
        rt_output = ParamRTOutput(data={
            "thrust_accel_mps2": list(accel),
            "fuel_pct": round(self._fuel_pct, 3),
            "mass_kg": self._mass_kg,
            "thrusting": thrusting,
            "prop_failed": self._failed,
        })
        mr = ParamMROutput(time=sim_t, state={
            "fuel_pct": self._fuel_pct,
            "burns": [dict(b) for b in self._burns],
            "formation": dict(self._formation) if self._formation else None,
            "failed": self._failed,
        })
        return StepResult(rt_output=rt_output, key_outputs=tuple(events), mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        state = dict(mr.state)
        self._fuel_pct = float(state.get("fuel_pct", self._fuel_pct))
        self._burns = [dict(b) for b in state.get("burns", [])]
        formation = state.get("formation")
        self._formation = dict(formation) if formation else None
        self._failed = bool(state.get("failed", False))
        return 0
