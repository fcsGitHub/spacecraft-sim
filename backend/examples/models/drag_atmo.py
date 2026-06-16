"""示例外部模型：指数大气阻力摄动（演示"无侵入扩展"工作流）。

加载方式（任选其一，无需修改仓库代码）：
1. 把本文件拷入 backend/data/models/，服务启动时自动加载；
2. 设置环境变量 SCSIM_MODEL_DIRS 指向本目录；
3. 脚本化：from simcore.registry import load_models_from_dir
           load_models_from_dir("backend/examples/models")

挂接方式：卫星定义的 `components` 字段中置于 thruster 与 orbit 之间，
输出 thrust_accel_mps2 = 上游推力 + 阻力加速度，由 orbit.j2 统一消费：

    satellites:
      - id: SAT-01
        ...
        components:
          - {name: thruster, model: prop.thruster}
          - {name: drag, model: perturb.drag_atmo, params: {cd: 2.2, area_m2: 12}}
          - {name: orbit, model: orbit.j2}
          - {name: attitude, model: aocs.simple}
          - {name: payload, model: payload.generic}

物理模型（演示级，研究可替换为 NRLMSISE-00 等大气模型）：
    rho(h) = rho_ref * exp(-(h - h_ref) / H)
    a_drag = -0.5 * rho * |v| * (Cd * A / m) * v
基于上一步环境快照中的本星位置/速度计算（与 thruster 相同的一步滞后约定），
忽略大气随地球旋转的相对速度修正。
"""

from __future__ import annotations

import math

from simcore import orbits
from simcore.model import Array6, AtomicModel, SimContext
from simcore.params import (
    ParamAttribute,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model


@register_model
class ExponentialDragModel(AtomicModel):
    model_type = "perturb.drag_atmo"
    display_name = "大气阻力(指数模型)"
    category = "perturbation"
    description = "指数大气密度 + 迎风阻力加速度，叠加至 thrust_accel_mps2 供轨道模型消费。"

    attribute_schema = {
        "cd": {"type": "number", "unit": "-", "default": 2.2, "desc": "阻力系数"},
        "area_m2": {"type": "number", "unit": "m²", "default": 5.0, "desc": "迎风面积"},
        "mass_kg": {"type": "number", "unit": "kg", "default": 1000.0,
                    "desc": "整星质量（assembly 自动注入卫星定义值）"},
        "rho_ref": {"type": "number", "unit": "kg/m³", "default": 3.8e-12,
                    "desc": "参考高度大气密度"},
        "h_ref_km": {"type": "number", "unit": "km", "default": 400.0, "desc": "参考高度"},
        "scale_h_km": {"type": "number", "unit": "km", "default": 58.0, "desc": "大气尺度高"},
    }

    def __init__(self) -> None:
        super().__init__()
        self._cd_a_over_m = 2.2 * 5.0 / 1000.0
        self._rho_ref = 3.8e-12
        self._h_ref_m = 400e3
        self._scale_h_m = 58e3

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        try:
            self._cd_a_over_m = (
                float(data["cd"]) * float(data["area_m2"]) / max(1.0, float(data["mass_kg"]))
            )
            self._rho_ref = max(0.0, float(data["rho_ref"]))
            self._h_ref_m = float(data["h_ref_km"]) * 1000.0
            self._scale_h_m = max(1000.0, float(data["scale_h_km"]) * 1000.0)
        except (KeyError, TypeError, ValueError):
            return 1
        return 0

    def sim_advance(
        self, ctx: SimContext, bjt: Array6, utc: Array6, step: float, rt_in: ParamRTInput
    ) -> StepResult:
        upstream_acc = rt_in.upstream.get("thrust_accel_mps2") or [0.0, 0.0, 0.0]
        ax = float(upstream_acc[0])
        ay = float(upstream_acc[1])
        az = float(upstream_acc[2])
        rho = 0.0
        drag_mag = 0.0

        own = (rt_in.env.get("entities") or {}).get(ctx.entity_id) or {}
        pos_km = own.get("pos_km")
        vel_kmps = own.get("vel_kmps")
        if step > 0 and pos_km and vel_kmps:
            r_m = math.sqrt(pos_km[0] ** 2 + pos_km[1] ** 2 + pos_km[2] ** 2) * 1000.0
            alt_m = r_m - orbits.RE_EARTH
            rho = self._rho_ref * math.exp(-(alt_m - self._h_ref_m) / self._scale_h_m)
            vx, vy, vz = vel_kmps[0] * 1000.0, vel_kmps[1] * 1000.0, vel_kmps[2] * 1000.0
            v_mag = math.sqrt(vx * vx + vy * vy + vz * vz)
            if v_mag > 1e-6:
                coef = -0.5 * rho * v_mag * self._cd_a_over_m
                ax += coef * vx
                ay += coef * vy
                az += coef * vz
                drag_mag = abs(coef) * v_mag

        rt_output = ParamRTOutput(data={
            "thrust_accel_mps2": [ax, ay, az],
            "drag_accel_mps2": drag_mag,
            "atmo_rho_kgpm3": rho,
        })
        return StepResult(
            rt_output=rt_output,
            mr_output=ParamMROutput(time=ctx.sim_time + step, state={}),
        )
