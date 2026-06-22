"""组合模型：挂载有序子模型，按挂载顺序推进，上游管道串联。

卫星=SatelliteCompositeModel；母星/子星/平台/载荷舱未来均可为组合。
本文件吸收原 assembly.py 的卫星派生属性与组件链构建逻辑。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from simcore.bus import MessageBus
from simcore.model import Array6, SimContext, SimModel
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
from simcore.registry import RegistryError, get_model_class
from simcore.scenario import SatelliteDef, ScenarioError

# 标准组件链：推进 -> 轨道 -> 姿态 -> 载荷（thruster 在 orbit 之前，
# 本步推力加速度经 upstream 传给轨道模型）
DEFAULT_CHAIN: tuple[tuple[str, str], ...] = (
    ("thruster", "prop.thruster"),
    ("orbit", "orbit.j2"),
    ("attitude", "aocs.simple"),
    ("payload", "payload.generic"),
)


@dataclass
class Mount:
    """组合的一个挂点：子模型 + 其卫星派生/自定义属性。"""

    name: str
    model: SimModel
    attrs: dict[str, Any]


def _join(prefix: str, name: str) -> str:
    return f"{prefix}/{name}" if prefix else name


class CompositeModel(SimModel):
    """模型容器：挂载 Atomic 或 Composite，确定性推进顺序 + 清晰数据流。"""

    model_kind = "composite"
    model_type = "composite"
    display_name = "组合模型"

    def __init__(self, mounts: list[Mount]) -> None:
        super().__init__()
        self.mounts = mounts

    # ---- 五接口 ----

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        self.attribute = attribute
        for m in self.mounts:
            child_ctx = replace(ctx, component=_join(ctx.component, m.name))
            code = m.model.sim_init(child_ctx, bjt, utc,
                                    ParamAttribute(info=attribute.info, data=m.attrs))
            if code != 0:
                return code
        return 0

    def sim_advance(self, ctx: SimContext, bjt: Array6, utc: Array6,
                    step: float, rt_in: ParamRTInput) -> StepResult:
        upstream: dict[str, Any] = dict(rt_in.upstream)
        key_outputs: list[ParamKeyOutput] = []
        messages: list[Any] = []
        children_mr: dict[str, Any] = {}
        for m in self.mounts:
            child_ctx = replace(ctx, component=_join(ctx.component, m.name))
            child_msgs = MessageBus.filter_for(rt_in.messages, set(m.model.subscribes))
            child_rt = ParamRTInput(env=rt_in.env, upstream=upstream, messages=child_msgs)
            res = m.model.sim_advance(child_ctx, bjt, utc, step, child_rt)
            upstream = {**upstream, **dict(res.rt_output.data)}
            key_outputs.extend(res.key_outputs)
            messages.extend(res.messages)
            children_mr[m.name] = {"time": res.mr_output.time, "state": dict(res.mr_output.state)}
        mr = ParamMROutput(time=ctx.sim_time + step, state={"children": children_mr})
        return StepResult(
            rt_output=ParamRTOutput(data=upstream),
            key_outputs=tuple(key_outputs),
            messages=tuple(messages),
            mr_output=mr,
        )

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        return self._route(ctr_in.target_model, lambda m, t: m.model.sim_ctr_response(
            replace(ctr_in, target_model=t)))

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        return self._route(dir_in.target_model, lambda m, t: m.model.sim_dir_response(
            replace(dir_in, target_model=t)))

    def sim_end(self, ctx: SimContext, bjt: Array6, utc: Array6, step: float) -> int:
        for m in self.mounts:
            child_ctx = replace(ctx, component=_join(ctx.component, m.name))
            m.model.sim_end(child_ctx, bjt, utc, step)
        return 0

    def sim_restore(self, mr: ParamMROutput) -> int:
        children = dict(mr.state).get("children", {})
        for m in self.mounts:
            payload = children.get(m.name)
            if payload:
                m.model.sim_restore(ParamMROutput(
                    time=float(payload.get("time", 0.0)),
                    state=dict(payload.get("state", {})),
                ))
        return 0

    # ---- 路由与查询 ----

    def _route(self, target: str, call: Callable[["Mount", str], int]) -> int:
        codes: list[int] = []
        for m in self.mounts:
            if not target:
                codes.append(call(m, ""))                        # 广播
            elif target == m.name:
                codes.append(call(m, ""))
            elif target.startswith(m.name + "/"):
                codes.append(call(m, target[len(m.name) + 1:]))  # 递归下发子路径
        return 0 if all(c == 0 for c in codes) else next(c for c in codes if c != 0)

    def all_subscribes(self) -> set[str]:
        out: set[str] = set()
        for m in self.mounts:
            if isinstance(m.model, CompositeModel):
                out |= m.model.all_subscribes()
            else:
                out |= set(m.model.subscribes)
        return out

    def component_names(self) -> list[str]:
        out: list[str] = []
        for m in self.mounts:
            out.append(m.name)
            if isinstance(m.model, CompositeModel):
                out.extend(_join(m.name, c) for c in m.model.component_names())
        return out

    def has_component(self, path: str) -> bool:
        return path in self.component_names()

    def describe(self) -> list[dict[str, Any]]:
        return [{"name": m.name, "model": m.model.model_type, "kind": m.model.model_kind}
                for m in self.mounts]


class SatelliteCompositeModel(CompositeModel):
    """卫星组合：组件链（推进→轨道→姿态→载荷，+ 可选相机/传感器）。"""

    model_type = "composite.satellite"
    display_name = "卫星组合"


def _satellite_attrs(sat: SatelliteDef, model_type: str) -> dict[str, Any]:
    """标准模型的卫星派生属性；自定义组件链同样自动注入，params 可覆盖。"""
    if model_type == "prop.thruster":
        return {"mass_kg": sat.mass, "fuel_pct": sat.fuel, "isp_s": 300.0, "burn_duration_s": 10.0}
    if model_type == "orbit.j2":
        return {"a_km": sat.orbit.a, "e": sat.orbit.e, "i_deg": sat.orbit.i,
                "raan_deg": sat.orbit.raan, "argp_deg": sat.orbit.argp, "m0_deg": sat.orbit.m0}
    if model_type == "aocs.simple":
        return {"mode": "对地定向"}
    if model_type == "payload.generic":
        return {"payload_type": sat.payload_type, "state": sat.payload_state,
                "power_w": sat.payload_power}
    # 非标准模型：注入整星质量，便于阻力/推进类摄动模型直接使用
    return {"mass_kg": sat.mass}


def _component_specs(sat: SatelliteDef) -> list[tuple[str, str, dict[str, Any]]]:
    """缺省标准链；卫星定义含非空 components 时按其声明（name/model/params）。"""
    custom = (sat.raw or {}).get("components")
    if custom:
        return [
            (str(c.get("name") or f"comp{i + 1}"), str(c.get("model") or ""), dict(c.get("params") or {}))
            for i, c in enumerate(custom)
        ]
    return [(name, mt, {}) for name, mt in DEFAULT_CHAIN]


def build_satellite(sat: SatelliteDef) -> SatelliteCompositeModel:
    """从卫星定义构建卫星组合模型。未注册的 model 抛 ScenarioError。"""
    mounts: list[Mount] = []
    for name, model_type, params in _component_specs(sat):
        try:
            cls = get_model_class(model_type)
        except RegistryError as exc:
            raise ScenarioError([{"loc": f"{sat.name}.components", "msg": str(exc)}]) from exc
        attrs = {**_satellite_attrs(sat, model_type), **params}
        mounts.append(Mount(name=name, model=cls(), attrs=attrs))
    return SatelliteCompositeModel(mounts)
