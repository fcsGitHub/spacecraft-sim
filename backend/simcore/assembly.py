"""实体组装：把场景卫星定义映射为原子模型组件序列。

对应规范"各单位提交的模型形式均为原子模型，由总集单位封装为组件模型和实体模型"。
组件顺序即推进顺序，上游组件输出通过 rt_in.upstream 传递给下游组件。

扩展方式（无需修改本文件）：
- 卫星定义中可选 `components` 字段直接声明组件链（见 build_components 文档）；
- 标准模型所需的卫星派生属性（轨道根数/质量/载荷等）自动注入，`params` 可覆盖。
"""

from __future__ import annotations

from typing import Any

from simcore.model import AtomicModel
from simcore.registry import RegistryError, get_model_class
from simcore.scenario import SatelliteDef, ScenarioError

ComponentSpec = tuple[str, type[AtomicModel], dict[str, Any]]

# 标准组件链：推进 -> 轨道 -> 姿态 -> 载荷（thruster 在 orbit 之前，
# 本步推力加速度经 upstream 传给轨道模型）
DEFAULT_CHAIN: tuple[tuple[str, str], ...] = (
    ("thruster", "prop.thruster"),
    ("orbit", "orbit.j2"),
    ("attitude", "aocs.simple"),
    ("payload", "payload.generic"),
)


def _satellite_attrs(sat: SatelliteDef, model_type: str) -> dict[str, Any]:
    """标准模型的卫星派生属性；自定义组件链同样自动注入，params 可覆盖。"""
    if model_type == "prop.thruster":
        return {
            "mass_kg": sat.mass,
            "fuel_pct": sat.fuel,
            "isp_s": 300.0,
            "burn_duration_s": 10.0,
        }
    if model_type == "orbit.j2":
        return {
            "a_km": sat.orbit.a,
            "e": sat.orbit.e,
            "i_deg": sat.orbit.i,
            "raan_deg": sat.orbit.raan,
            "argp_deg": sat.orbit.argp,
            "m0_deg": sat.orbit.m0,
        }
    if model_type == "aocs.simple":
        return {"mode": "对地定向"}
    if model_type == "payload.generic":
        return {
            "payload_type": sat.payload_type,
            "state": sat.payload_state,
            "power_w": sat.payload_power,
        }
    # 非标准模型：注入整星质量，便于阻力/推进类摄动模型直接使用
    return {"mass_kg": sat.mass}


def build_components(sat: SatelliteDef) -> list[ComponentSpec]:
    """构建卫星组件链。

    缺省为标准链 thruster -> orbit -> attitude -> payload；
    卫星定义含非空 `components` 数组时按其声明组装：

        components:
          - {name: thruster, model: prop.thruster}
          - {name: drag, model: perturb.drag_atmo, params: {cd: 2.2, area_m2: 12}}
          - {name: orbit, model: orbit.j2}
          - {name: attitude, model: aocs.simple}
          - {name: payload, model: payload.generic}

    指令模板默认面向标准组件名（thruster/orbit/attitude/payload），
    自定义链如需响应指令请沿用同名组件。未注册的 model 抛 ScenarioError。
    """
    custom = (sat.raw or {}).get("components")
    if custom:
        specs = [
            (
                str(comp.get("name") or f"comp{idx + 1}"),
                str(comp.get("model") or ""),
                dict(comp.get("params") or {}),
            )
            for idx, comp in enumerate(custom)
        ]
    else:
        specs = [(name, model_type, {}) for name, model_type in DEFAULT_CHAIN]

    out: list[ComponentSpec] = []
    for name, model_type, params in specs:
        try:
            cls = get_model_class(model_type)
        except RegistryError as exc:
            raise ScenarioError(
                [{"loc": f"{sat.name}.components", "msg": str(exc)}]
            ) from exc
        out.append((name, cls, {**_satellite_attrs(sat, model_type), **params}))
    return out
