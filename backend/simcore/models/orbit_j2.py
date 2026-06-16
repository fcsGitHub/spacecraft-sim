"""J2 轨道动力学模型（规范模板示例 MdlSatPlat 的 Python 对应）。

实时输入（upstream）：thrust_accel_mps2 推力加速度 [ax,ay,az] (ECI, m/s²)
实时输出：pos_km / vel_kmps (ECI)、alt_km、speed_kmps、orbit（osculating 根数,
          与前端轨道线绘制格式一致：a km / e / i / raan / argp / M0 °）、
          lat_deg / lon_deg 星下点

性能约定：位置/速度/高度/星下点每步精确输出；osculating 根数换算较贵，
按 ELEMENTS_REFRESH_S 间隔缓存刷新（点火期间与导调重置后立即刷新），
前端轨道线重绘有变化阈值，缓存延迟不影响显示。
"""

from __future__ import annotations

import math
from typing import Any

from simcore import orbits
from simcore.model import Array6, AtomicModel, SimContext
from simcore.params import (
    ParamAttribute,
    ParamDirInput,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
    ParamRTOutput,
    StepResult,
)
from simcore.registry import register_model
from simcore.timebase import OMEGA_EARTH_RAD_PER_S, gmst_rad, parse_epoch

TWO_PI = 2.0 * math.pi
ELEMENTS_REFRESH_S = 10.0   # osculating 根数缓存最长刷新间隔（仿真秒）
REENTRY_ALT_M = 120e3       # 再入告警高度
REENTRY_REARM_ALT_M = 140e3  # 回升至此高度以上重新武装告警（迟滞，防事件洪泛）


@register_model
class J2OrbitModel(AtomicModel):
    model_type = "orbit.j2"
    display_name = "J2轨道动力学"
    category = "orbit"
    description = "二体+J2摄动轨道递推（RK4），支持推力加速度输入与导调轨道重置。"

    attribute_schema = {
        "a_km": {"type": "number", "unit": "km", "default": 6878.0, "desc": "半长轴"},
        "e": {"type": "number", "unit": "-", "default": 0.001, "desc": "偏心率"},
        "i_deg": {"type": "number", "unit": "°", "default": 51.6, "desc": "轨道倾角"},
        "raan_deg": {"type": "number", "unit": "°", "default": 0.0, "desc": "升交点赤经"},
        "argp_deg": {"type": "number", "unit": "°", "default": 0.0, "desc": "近地点幅角"},
        "m0_deg": {"type": "number", "unit": "°", "default": 0.0, "desc": "初始平近点角"},
        "enable_j2": {"type": "boolean", "unit": "-", "default": True, "desc": "是否启用J2摄动"},
    }
    ctr_commands = {}
    dir_commands = {
        "set_orbit": {
            "desc": "导调重置轨道根数（参数与属性同名，缺省保持当前值）",
            "params": {
                "a_km": {"type": "number", "unit": "km", "desc": "半长轴"},
                "e": {"type": "number", "unit": "-", "desc": "偏心率"},
                "i_deg": {"type": "number", "unit": "°", "desc": "倾角"},
                "raan_deg": {"type": "number", "unit": "°", "desc": "升交点赤经"},
                "argp_deg": {"type": "number", "unit": "°", "desc": "近地点幅角"},
                "m0_deg": {"type": "number", "unit": "°", "desc": "平近点角"},
            },
        },
    }

    def __init__(self) -> None:
        super().__init__()
        self._state: orbits.State = (orbits.RE_EARTH + 500e3, 0, 0, 0, 7612, 0)
        self._enable_j2 = True
        self._gmst0 = 0.0  # 历元 GMST（rad），星下点按地球自转率线性递推
        self._orbit_cache: dict[str, Any] | None = None  # 缓存的 orbit 根数 + period_s
        self._orbit_cache_t = -1e18
        self._reentry_warned = False  # 再入告警迟滞标志

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        try:
            nu_deg = orbits.mean_to_true_deg(float(data["m0_deg"]), float(data["e"]))
            self._state = orbits.elements_to_state(
                float(data["a_km"]) * 1000.0, float(data["e"]), float(data["i_deg"]),
                float(data["raan_deg"]), float(data["argp_deg"]), nu_deg,
            )
        except (ValueError, KeyError, TypeError):
            return 1
        self._enable_j2 = bool(data.get("enable_j2", True))
        self._gmst0 = gmst_rad(parse_epoch(ctx.engine.scenario.epoch_utc))
        self._orbit_cache = None
        return 0

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        if dir_in.name != "set_orbit":
            return 0
        current = orbits.state_to_elements(self._state)
        merged = {
            "a_km": float(dir_in.params.get("a_km", current["a_m"] / 1000.0)),
            "e": float(dir_in.params.get("e", current["e"])),
            "i_deg": float(dir_in.params.get("i_deg", current["i_deg"])),
            "raan_deg": float(dir_in.params.get("raan_deg", current["raan_deg"])),
            "argp_deg": float(dir_in.params.get("argp_deg", current["argp_deg"])),
        }
        nu_deg = (
            orbits.mean_to_true_deg(float(dir_in.params["m0_deg"]), merged["e"])
            if "m0_deg" in dir_in.params
            else current["nu_deg"]
        )
        try:
            self._state = orbits.elements_to_state(
                merged["a_km"] * 1000.0, merged["e"], merged["i_deg"],
                merged["raan_deg"], merged["argp_deg"], nu_deg,
            )
        except ValueError:
            return 1
        self._orbit_cache = None  # 轨道重置后下一步立即刷新根数
        return 0

    def sim_advance(
        self, ctx: SimContext, bjt: Array6, utc: Array6, step: float, rt_in: ParamRTInput
    ) -> StepResult:
        accel_raw = rt_in.upstream.get("thrust_accel_mps2")
        accel = (
            (float(accel_raw[0]), float(accel_raw[1]), float(accel_raw[2]))
            if accel_raw
            else (0.0, 0.0, 0.0)
        )
        self._state = orbits.propagate(self._state, step, accel, self._enable_j2)
        sim_t = ctx.sim_time + step
        rx, ry, rz, vx, vy, vz = self._state
        r_mag = math.sqrt(rx * rx + ry * ry + rz * rz)
        v_mag = math.sqrt(vx * vx + vy * vy + vz * vz)
        alt_m = r_mag - orbits.RE_EARTH
        gmst = (self._gmst0 + OMEGA_EARTH_RAD_PER_S * sim_t) % TWO_PI
        geo = orbits.eci_to_geodetic((rx, ry, rz), gmst)

        # osculating 根数换算较贵：点火期间每步刷新，否则按间隔刷新缓存
        thrusting = accel != (0.0, 0.0, 0.0)
        if (self._orbit_cache is None or thrusting
                or sim_t - self._orbit_cache_t >= ELEMENTS_REFRESH_S):
            elements = orbits.state_to_elements(self._state)
            self._orbit_cache = {
                "orbit": {
                    "a": round(elements["a_m"] / 1000.0, 3),
                    "e": round(elements["e"], 6),
                    "i": round(elements["i_deg"], 4),
                    "raan": round(elements["raan_deg"], 4),
                    "argp": round(elements["argp_deg"], 4),
                    "M0": round(orbits.true_to_mean_deg(elements["nu_deg"], elements["e"]), 4),
                },
                "period_s": round(elements["period_s"], 1),
            }
            self._orbit_cache_t = sim_t

        key_outputs: tuple[ParamKeyOutput, ...] = ()
        if alt_m < REENTRY_ALT_M:
            if not self._reentry_warned:  # 迟滞：跌破只告警一次，防止逐步刷屏
                self._reentry_warned = True
                key_outputs = (
                    ParamKeyOutput(
                        time=sim_t, entity_id=ctx.entity_id, source=ctx.component,
                        level="critical", event="系统",
                        message=f"{ctx.entity_id} 轨道高度过低 {alt_m / 1000:.0f} km，即将再入",
                    ),
                )
        elif alt_m > REENTRY_REARM_ALT_M:
            self._reentry_warned = False

        rt_output = ParamRTOutput(data={
            "pos_km": [round(rx / 1000.0, 4), round(ry / 1000.0, 4), round(rz / 1000.0, 4)],
            "vel_kmps": [round(vx / 1000.0, 6), round(vy / 1000.0, 6), round(vz / 1000.0, 6)],
            "alt_km": round(alt_m / 1000.0, 3),
            "speed_kmps": round(v_mag / 1000.0, 5),
            "lat_deg": round(geo["lat_deg"], 4),
            "lon_deg": round(geo["lon_deg"], 4),
            "orbit": self._orbit_cache["orbit"],
            "period_s": self._orbit_cache["period_s"],
        })
        mr = ParamMROutput(time=sim_t, state={"state": list(self._state)})
        return StepResult(rt_output=rt_output, key_outputs=key_outputs, mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        raw = mr.state.get("state")
        if not isinstance(raw, list) or len(raw) != 6:
            return 1
        self._state = (
            float(raw[0]), float(raw[1]), float(raw[2]),
            float(raw[3]), float(raw[4]), float(raw[5]),
        )
        self._orbit_cache = None  # 恢复后下一步立即重算根数，避免陈旧缓存
        return 0
