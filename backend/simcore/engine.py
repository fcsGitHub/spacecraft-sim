"""仿真引擎：实体组装、步进推进、指令注入、接近预警、状态快照。

引擎本身是同步、确定性的（同场景 + 同种子 + 同指令序列 → 逐位复现）；
实时调度（暂停/倍速/异步指令队列）由上层 server.runtime 承担。
"""

from __future__ import annotations

import bisect
import random
from dataclasses import dataclass, field
from typing import Any

from simcore.assembly import build_components
from simcore.model import AtomicModel, SimContext
from simcore.params import (
    EntityInfo,
    ParamAttribute,
    ParamCtrInput,
    ParamDirInput,
    ParamKeyOutput,
    ParamMROutput,
    ParamRTInput,
)
from simcore.scenario import Scenario
from simcore.timebase import SimClock, parse_epoch

DEFAULT_ALERT_THRESHOLD_KM = 100.0


@dataclass(frozen=True)
class Frame:
    """单步仿真快照（不可变），用于显示、录制与外发。"""

    t: float
    utc: str
    entities: dict[str, dict[str, Any]]
    events: tuple[ParamKeyOutput, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "t": self.t,
            "utc": self.utc,
            "entities": self.entities,
            "events": [
                {
                    "t": e.time,
                    "target": e.entity_id,
                    "source": e.source,
                    "level": e.level,
                    "type": e.event,
                    "text": e.message,
                    "data": dict(e.data),
                }
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
    ev_type: str = "指令"   # 时间线分类：机动/载荷/姿态/系统/指令
    source: str = "command" # event=场景预设 / command=运行中注入


@dataclass
class _Component:
    name: str
    model: AtomicModel
    ctx: SimContext
    last_mr: ParamMROutput = field(default_factory=ParamMROutput)


@dataclass
class _Entity:
    info: EntityInfo
    components: list[_Component]


class EngineError(Exception):
    pass


class SimulationEngine:
    """根据场景组装实体并推进仿真。

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
        self.alert_threshold_km = DEFAULT_ALERT_THRESHOLD_KM
        self.initialized = False
        self.ended = False
        self._entities: dict[str, _Entity] = {}
        self._schedule: list[ScheduledCommand] = []
        self._schedule_keys: list[float] = []
        self._alert_seen: set[str] = set()
        self.last_entity_states: dict[str, dict[str, Any]] = {}
        self.last_frame: Frame | None = None
        self._build_entities()

    # ---- 组装 ----

    def _build_entities(self) -> None:
        for sat in self.scenario.satellites:
            components = [
                _Component(
                    name=name, model=model_cls(),
                    ctx=SimContext(engine=self, entity_id=sat.sat_id, component=name),
                )
                for name, model_cls, _attrs in build_components(sat)
            ]
            info = EntityInfo(
                entity_id=sat.sat_id, name=sat.name, group=sat.group, faction=sat.faction
            )
            self._entities[sat.sat_id] = _Entity(info=info, components=components)

    # ---- 生命周期 ----

    def init(self) -> None:
        """调用全部模型的 sim_init（规范：仿真开始时调用一次）。"""
        if self.initialized:
            raise EngineError("引擎已初始化")
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        for sat in self.scenario.satellites:
            entity = self._entities[sat.sat_id]
            for (comp_name, _cls, attrs), comp in zip(build_components(sat), entity.components):
                attribute = ParamAttribute(info=entity.info, data=attrs)
                code = comp.model.sim_init(comp.ctx, bjt, utc, attribute)
                if code != 0:
                    raise EngineError(
                        f"实体[{entity.info.name}] 组件[{comp_name}] sim_init 返回异常码 {code}"
                    )
        self.initialized = True
        self.last_frame = self._advance_all(0.0)  # t=0 初始状态帧，不推进时钟

    @property
    def finished(self) -> bool:
        return self.clock.t >= self.scenario.duration_s - 1e-9

    def step(self, step_s: float | None = None) -> Frame:
        """推进一个仿真步：先触发到期计划指令，再推进全部实体。"""
        if not self.initialized:
            raise EngineError("引擎未初始化，请先调用 init()")
        if self.ended:
            raise EngineError("引擎已结束")
        step = step_s if step_s is not None else self.step_s
        fired = self._fire_due_commands()
        return self._advance_all(step, extra_events=fired)

    def end(self) -> None:
        """调用全部模型的 sim_end（规范：仿真停止时调用）。"""
        if self.ended:
            return
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        for entity in self._entities.values():
            for comp in entity.components:
                comp.model.sim_end(comp.ctx, bjt, utc, self.step_s)
        self.ended = True

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
        entity = self._entities.get(cmd.entity_id)
        if entity is None:
            raise EngineError(f"实体不存在: {cmd.entity_id}")
        if cmd.channel not in ("ctr", "dir"):
            raise EngineError(f"未知指令通道: {cmd.channel}（应为 ctr 或 dir）")
        targets = [c for c in entity.components if not cmd.target_model or c.name == cmd.target_model]
        if cmd.target_model and not targets:
            raise EngineError(f"实体[{entity.info.name}] 不存在组件: {cmd.target_model}")
        codes: list[int] = []
        for comp in targets:
            if cmd.channel == "ctr":
                codes.append(comp.model.sim_ctr_response(ParamCtrInput(
                    entity_id=cmd.entity_id, target_model=comp.name, name=cmd.name,
                    params=cmd.params, time=self.clock.t,
                )))
            else:
                codes.append(comp.model.sim_dir_response(ParamDirInput(
                    entity_id=cmd.entity_id, target_model=comp.name, name=cmd.name,
                    params=cmd.params, time=self.clock.t,
                )))
        ok = all(c == 0 for c in codes)
        return ParamKeyOutput(
            time=self.clock.t,
            entity_id=cmd.entity_id,
            source=cmd.target_model or "*",
            level="info" if ok else "warning",
            event=cmd.ev_type if ok else "指令拒绝",
            message=cmd.label or f"{cmd.entity_id} {cmd.name}",
            data={"channel": cmd.channel, "name": cmd.name,
                  "params": dict(cmd.params), "codes": codes, "source": cmd.source},
        )

    def pending_commands(self) -> list[ScheduledCommand]:
        """尚未触发的计划指令（按时间序）。供预推演沙箱携带未来预约机动/事件。

        ScheduledCommand 为 frozen dataclass，返回浅拷贝列表即可安全复用。
        """
        return list(self._schedule)

    def _fire_due_commands(self) -> list[ParamKeyOutput]:
        fired: list[ParamKeyOutput] = []
        while self._schedule and self._schedule_keys[0] <= self.clock.t + 1e-9:
            cmd = self._schedule.pop(0)
            self._schedule_keys.pop(0)
            fired.append(self.inject_now(cmd))
        return fired

    # ---- 推进 ----

    def _advance_all(self, step: float, extra_events: list[ParamKeyOutput] | None = None) -> Frame:
        env = self._build_env()
        bjt, utc = self.clock.bjt_array, self.clock.utc_array
        new_states: dict[str, dict[str, Any]] = {}
        all_events: list[ParamKeyOutput] = list(extra_events or [])

        for entity in self._entities.values():
            upstream: dict[str, Any] = {
                "id": entity.info.entity_id,
                "name": entity.info.name,
                "group": entity.info.group,
                "faction": entity.info.faction,
            }
            for comp in entity.components:
                # upstream 每轮重新合并生成新字典，传入的旧字典不会被改写，无需防御性拷贝
                rt_in = ParamRTInput(env=env, upstream=upstream)
                result = comp.model.sim_advance(comp.ctx, bjt, utc, step, rt_in)
                upstream = {**upstream, **result.rt_output.data}
                all_events.extend(result.key_outputs)
                comp.last_mr = result.mr_output
            new_states[entity.info.entity_id] = upstream

        if step > 0:
            self.clock = self.clock.advanced(step)
        self.last_entity_states = new_states
        all_events.extend(self._check_proximity(new_states))
        frame = Frame(
            t=self.clock.t,
            utc=self.clock.utc_iso,
            entities=new_states,
            events=tuple(all_events),
        )
        self.last_frame = frame
        return frame

    def _build_env(self) -> dict[str, Any]:
        """环境数据：上一步全部实体状态快照（避免本步内顺序耦合）。"""
        return {
            "sim_time": self.clock.t,
            "entities": self.last_entity_states,
        }

    def _check_proximity(self, states: dict[str, dict[str, Any]]) -> list[ParamKeyOutput]:
        """接近预警裁决：任意星对距离低于门限时产生一次预警事件。"""
        alerts: list[ParamKeyOutput] = []
        ids = list(states.keys())
        threshold_sq = self.alert_threshold_km ** 2
        for i in range(len(ids)):
            pos_i = states[ids[i]].get("pos_km")
            if not pos_i:
                continue
            for j in range(i + 1, len(ids)):
                pos_j = states[ids[j]].get("pos_km")
                if not pos_j:
                    continue
                dx = pos_i[0] - pos_j[0]
                dy = pos_i[1] - pos_j[1]
                dz = pos_i[2] - pos_j[2]
                dist_sq = dx * dx + dy * dy + dz * dz
                pair = f"{ids[i]}|{ids[j]}"
                if dist_sq < threshold_sq:
                    dist = dist_sq ** 0.5
                    if pair not in self._alert_seen:
                        self._alert_seen.add(pair)
                        alerts.append(ParamKeyOutput(
                            time=self.clock.t,
                            entity_id=ids[i],
                            source="proximity",
                            level="warning",
                            event="预警",
                            message=f"{ids[i]} ↔ {ids[j]} 接近 {dist:.0f} km",
                            data={"pair": [ids[i], ids[j]], "dist_km": round(dist, 2)},
                        ))
        return alerts

    # ---- 数据恢复 ----

    def snapshot_mr(self) -> dict[str, Any]:
        """采集全部组件的恢复数据（规范：模型数据恢复结构体）。"""
        return {
            "t": self.clock.t,
            "components": {
                f"{eid}/{comp.name}": {"time": comp.last_mr.time, "state": dict(comp.last_mr.state)}
                for eid, entity in self._entities.items()
                for comp in entity.components
            },
        }

    def restore_mr(self, snapshot: dict[str, Any]) -> None:
        """从恢复数据还原（断点续算）。"""
        self.clock = SimClock(epoch_utc=self.clock.epoch_utc, t=float(snapshot["t"]))
        for key, payload in snapshot.get("components", {}).items():
            eid, comp_name = key.split("/", 1)
            entity = self._entities.get(eid)
            if entity is None:
                continue
            for comp in entity.components:
                if comp.name == comp_name:
                    comp.model.sim_restore(
                        ParamMROutput(time=float(payload["time"]), state=dict(payload["state"]))
                    )

    # ---- 查询 ----

    def entity_infos(self) -> list[dict[str, Any]]:
        return [
            {
                "id": e.info.entity_id,
                "name": e.info.name,
                "group": e.info.group,
                "faction": e.info.faction,
                "components": [
                    {"name": c.name, "model": c.model.model_type} for c in e.components
                ],
            }
            for e in self._entities.values()
        ]
