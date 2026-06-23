"""仿真引擎：组合实体装配、两相步进、发布订阅总线、裁决调度、状态快照。

单步两相：相位1 全部组合实体推进并发布消息；相位2 裁决读本拍消息评判。
实体间/结果回传延迟一拍，保持逐位复现。实时调度由上层 server.runtime 承担。
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field
from typing import Any

from simcore.bus import BusMessage, MessageBus
from simcore.perception import merge_perception
from simcore.composite import SatelliteCompositeModel, build_satellite
from simcore.model import AdjudicationModel, SimContext
from simcore.params import (
    EntityInfo,
    ParamAttribute,
    ParamCtrInput,
    ParamDirInput,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
)
from simcore.registry import get_model_class
from simcore.scenario import AdjudicationDef, Scenario
from simcore.sun import sun_unit_eci
from simcore.timebase import SimClock, parse_epoch

DEFAULT_ALERT_THRESHOLD_KM = 100.0


@dataclass(frozen=True)
class Frame:
    """单步仿真快照（不可变），用于显示、录制与外发。"""

    t: float
    utc: str
    entities: dict[str, dict[str, Any]]
    events: tuple[ParamKeyOutput, ...] = ()
    perception: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "utc": self.utc,
            "entities": self.entities,
            "perception": self.perception,
            "events": [
                {"t": e.time, "target": e.entity_id, "source": e.source, "level": e.level,
                 "type": e.event, "text": e.message, "data": dict(e.data)}
                for e in self.events
            ],
        }


@dataclass(frozen=True)
class ScheduledCommand:
    """计划指令：预设事件与异步注入指令统一走此结构。"""

    t: float
    entity_id: str
    channel: str            # ctr / dir
    name: str               # 模型指令名
    target_model: str = ""  # 目标组件，空为广播
    params: dict[str, Any] = field(default_factory=dict)
    label: str = ""         # 显示文本
    ev_type: str = "指令"   # 时间线分类：机动/载荷/姿态/系统/拍照/指令
    source: str = "command"  # event=场景预设 / command=运行中注入


@dataclass
class _Entity:
    info: EntityInfo
    model: SatelliteCompositeModel
    ctx: SimContext
    last_mr: ParamMROutput = field(default_factory=ParamMROutput)


@dataclass
class _Adjud:
    model: AdjudicationModel
    ctx: SimContext
    attrs: dict[str, Any]
    last_mr: ParamMROutput = field(default_factory=ParamMROutput)


class EngineError(Exception):
    pass


class SimulationEngine:
    """根据场景组装组合实体并两相推进仿真。

    用法：
        engine = SimulationEngine(scenario)
        engine.init()
        while not engine.finished:
            frame = engine.step()
        engine.end()
    """

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        self.clock = SimClock(epoch_utc=parse_epoch(scenario.epoch_utc))
        self.step_s = scenario.step_s
        self.rng = random.Random(scenario.seed)
        self.initialized = False
        self.ended = False
        self.bus = MessageBus()
        self._entities: dict[str, _Entity] = {}
        self._adjuds: list[_Adjud] = []
        self._inbox: dict[str, tuple[BusMessage, ...]] = {}
        self._schedule: list[ScheduledCommand] = []
        self._schedule_keys: list[float] = []
        self.last_entity_states: dict[str, dict[str, Any]] = {}
        self.last_frame: Frame | None = None
        self._build_entities()
        self._build_adjudications()

    # ---- 组装 ----

    def _build_entities(self) -> None:
        for sat in self.scenario.satellites:
            info = EntityInfo(entity_id=sat.sat_id, name=sat.name,
                              group=sat.group, faction=sat.faction, parent=sat.parent)
            self._entities[sat.sat_id] = _Entity(
                info=info, model=build_satellite(sat),
                ctx=SimContext(engine=self, entity_id=sat.sat_id, component=""))

    def _build_adjudications(self) -> None:
        defs = self.scenario.adjudications or (
            AdjudicationDef("adjud.proximity", {"threshold_km": DEFAULT_ALERT_THRESHOLD_KM}),)
        for d in defs:
            cls = get_model_class(d.type)
            model = cls()
            self._adjuds.append(_Adjud(
                model=model, attrs=dict(d.params),
                ctx=SimContext(engine=self, entity_id="", component=f"adjud:{d.type}")))

    # ---- 兼容接口：接近预警门限代理到 adjud.proximity（保持 server/predict 不变） ----

    @property
    def alert_threshold_km(self) -> float:
        for adj in self._adjuds:
            if adj.model.model_type == "adjud.proximity":
                return float(getattr(adj.model, "threshold_km", DEFAULT_ALERT_THRESHOLD_KM))
        return DEFAULT_ALERT_THRESHOLD_KM

    @alert_threshold_km.setter
    def alert_threshold_km(self, km: float) -> None:
        for adj in self._adjuds:
            if adj.model.model_type == "adjud.proximity":
                adj.model.threshold_km = float(km)

    # ---- 生命周期 ----

    def init(self) -> None:
        if self.initialized:
            raise EngineError("引擎已初始化")
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        for ent in self._entities.values():
            code = ent.model.sim_init(ent.ctx, bjt, utc, ParamAttribute(info=ent.info, data={}))
            if code != 0:
                raise EngineError(f"实体[{ent.info.name}] sim_init 返回异常码 {code}")
        for adj in self._adjuds:
            code = adj.model.sim_init(adj.ctx, bjt, utc, ParamAttribute(data=adj.attrs))
            if code != 0:
                raise EngineError(f"裁决[{adj.model.model_type}] sim_init 返回异常码 {code}")
        self.initialized = True
        # t=0 初始帧：仅相位1，总线空、不跑裁决
        new_states, _ev, _pub = self._advance_entities(0.0, self._env(self.last_entity_states))
        self.last_entity_states = new_states
        self.last_frame = Frame(t=self.clock.t, utc=self.clock.utc_iso, entities=new_states)

    @property
    def finished(self) -> bool:
        return self.clock.t >= self.scenario.duration_s - 1e-9

    def step(self, step_s: float | None = None) -> Frame:
        if not self.initialized:
            raise EngineError("引擎未初始化，请先调用 init()")
        if self.ended:
            raise EngineError("引擎已结束")
        step = step_s if step_s is not None else self.step_s
        fired = self._fire_due_commands()
        sun_hat = sun_unit_eci(self.clock.utc)

        env1 = self._env(self.last_entity_states, sun_hat)
        new_states, ent_events, published1 = self._advance_entities(step, env1)

        env2 = self._env(new_states, sun_hat, sim_time=self.clock.t + step)
        adjud_events, published2, perception = self._advance_adjuds(step, env2, published1)

        if step > 0:
            self.clock = self.clock.advanced(step)
        self.last_entity_states = new_states
        self._inbox = self._route_to_entities(published1 + published2)

        frame = Frame(t=self.clock.t, utc=self.clock.utc_iso, entities=new_states,
                      events=tuple([*fired, *ent_events, *adjud_events]),
                      perception=perception)
        self.last_frame = frame
        return frame

    def end(self) -> None:
        if self.ended:
            return
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        for ent in self._entities.values():
            ent.model.sim_end(ent.ctx, bjt, utc, self.step_s)
        self.ended = True

    # ---- 推进相位 ----

    def _env(self, states: dict[str, dict[str, Any]],
             sun_hat: tuple[float, float, float] | None = None,
             sim_time: float | None = None) -> dict[str, Any]:
        return {
            "sim_time": self.clock.t if sim_time is None else sim_time,
            "entities": states,
            "sun_eci": sun_hat if sun_hat is not None else sun_unit_eci(self.clock.utc),
        }

    def _advance_entities(self, step: float, env: dict[str, Any]):
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        new_states: dict[str, dict[str, Any]] = {}
        key_outputs: list[ParamKeyOutput] = []
        published: list[BusMessage] = []
        for ent in self._entities.values():
            seed = {"id": ent.info.entity_id, "name": ent.info.name,
                    "group": ent.info.group, "faction": ent.info.faction}
            rt_in = ParamRTInput(env=env, upstream=seed,
                                 messages=self._inbox.get(ent.info.entity_id, ()))
            res = ent.model.sim_advance(ent.ctx, bjt, utc, step, rt_in)
            published.extend(self.bus.stamp(res.messages, source=ent.info.entity_id))
            key_outputs.extend(res.key_outputs)
            ent.last_mr = res.mr_output
            new_states[ent.info.entity_id] = dict(res.rt_output.data)
        return new_states, key_outputs, tuple(published)

    def _advance_adjuds(self, step: float, env: dict[str, Any], published1: tuple[BusMessage, ...]):
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        events: list[ParamKeyOutput] = []
        published: list[BusMessage] = []
        perception_parts: list[dict[str, Any]] = []
        for adj in self._adjuds:
            msgs = MessageBus.filter_for(published1, set(adj.model.subscribes))
            rt_in = ParamRTInput(env=env, upstream={}, messages=msgs)
            res = adj.model.sim_advance(adj.ctx, bjt, utc, step, rt_in)
            published.extend(self.bus.stamp(res.messages, source=adj.model.model_type))
            events.extend(res.key_outputs)
            adj.last_mr = res.mr_output
            part = res.rt_output.data.get("perception")
            if part:
                perception_parts.append(part)
        return events, tuple(published), merge_perception(perception_parts)

    def _route_to_entities(self, messages: tuple[BusMessage, ...]) -> dict[str, tuple[BusMessage, ...]]:
        inbox: dict[str, tuple[BusMessage, ...]] = {}
        for ent in self._entities.values():
            sel = MessageBus.filter_for(messages, ent.model.all_subscribes())
            if sel:
                inbox[ent.info.entity_id] = sel
        return inbox

    # ---- 指令 ----

    def schedule_command(self, cmd: ScheduledCommand) -> None:
        """按时间序插入计划指令（异步注入与预设事件统一入口）。"""
        if cmd.entity_id not in self._entities:
            raise EngineError(f"实体不存在: {cmd.entity_id}")
        idx = bisect.bisect_right(self._schedule_keys, cmd.t)
        self._schedule.insert(idx, cmd)
        self._schedule_keys.insert(idx, cmd.t)

    def inject_now(self, cmd: ScheduledCommand) -> ParamKeyOutput:
        """立即执行指令（在两个仿真步之间调用，对应规范的异步指控/导调输入）。"""
        ent = self._entities.get(cmd.entity_id)
        if ent is None:
            raise EngineError(f"实体不存在: {cmd.entity_id}")
        if cmd.channel not in ("ctr", "dir"):
            raise EngineError(f"未知指令通道: {cmd.channel}（应为 ctr 或 dir）")
        if cmd.target_model and not ent.model.has_component(cmd.target_model):
            raise EngineError(f"实体[{ent.info.name}] 不存在组件: {cmd.target_model}")
        if cmd.channel == "ctr":
            code = ent.model.sim_ctr_response(ParamCtrInput(
                entity_id=cmd.entity_id, target_model=cmd.target_model,
                name=cmd.name, params=cmd.params, time=self.clock.t))
        else:
            code = ent.model.sim_dir_response(ParamDirInput(
                entity_id=cmd.entity_id, target_model=cmd.target_model,
                name=cmd.name, params=cmd.params, time=self.clock.t))
        ok = code == 0
        return ParamKeyOutput(
            time=self.clock.t, entity_id=cmd.entity_id, source=cmd.target_model or "*",
            level="info" if ok else "warning",
            event=cmd.ev_type if ok else "指令拒绝",
            message=cmd.label or f"{cmd.entity_id} {cmd.name}",
            data={"channel": cmd.channel, "name": cmd.name,
                  "params": dict(cmd.params), "code": code, "source": cmd.source})

    def pending_commands(self) -> list[ScheduledCommand]:
        """尚未触发的计划指令（按时间序）。供预推演沙箱携带未来预约机动/事件。"""
        return list(self._schedule)

    def _fire_due_commands(self) -> list[ParamKeyOutput]:
        fired: list[ParamKeyOutput] = []
        while self._schedule and self._schedule_keys[0] <= self.clock.t + 1e-9:
            cmd = self._schedule.pop(0)
            self._schedule_keys.pop(0)
            fired.append(self.inject_now(cmd))
        return fired

    # ---- 数据恢复 ----

    def snapshot_mr(self) -> dict[str, Any]:
        """采集组合实体 + 裁决 + 总线缓冲的恢复数据（规范：模型数据恢复结构体）。"""
        return {
            "t": self.clock.t,
            "entities": {eid: {"time": e.last_mr.time, "state": dict(e.last_mr.state)}
                         for eid, e in self._entities.items()},
            "adjudications": {adj.model.model_type:
                              {"time": adj.last_mr.time, "state": dict(adj.last_mr.state)}
                              for adj in self._adjuds},
            "inbox": {eid: [m.to_dict() for m in msgs] for eid, msgs in self._inbox.items()},
        }

    def restore_mr(self, snapshot: dict[str, Any]) -> None:
        """从恢复数据还原（断点续算）：组合树 + 裁决 + 延迟总线缓冲。"""
        self.clock = SimClock(epoch_utc=self.clock.epoch_utc, t=float(snapshot["t"]))
        for eid, payload in snapshot.get("entities", {}).items():
            ent = self._entities.get(eid)
            if ent is not None:
                mr = ParamMROutput(time=float(payload["time"]), state=dict(payload["state"]))
                ent.model.sim_restore(mr)
                ent.last_mr = mr
        adj_by_type = {adj.model.model_type: adj for adj in self._adjuds}
        for atype, payload in snapshot.get("adjudications", {}).items():
            adj = adj_by_type.get(atype)
            if adj is not None:
                mr = ParamMROutput(time=float(payload["time"]), state=dict(payload["state"]))
                adj.model.sim_restore(mr)
                adj.last_mr = mr
        self._inbox = {eid: tuple(BusMessage.from_dict(d) for d in msgs)
                       for eid, msgs in snapshot.get("inbox", {}).items()}

    # ---- 查询 ----

    def entity_infos(self) -> list[dict[str, Any]]:
        return [
            {"id": e.info.entity_id, "name": e.info.name, "group": e.info.group,
             "faction": e.info.faction, "parent": e.info.parent,
             "components": e.model.describe()}
            for e in self._entities.values()
        ]
