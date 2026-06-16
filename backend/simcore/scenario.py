"""场景定义：加载、校验前端场景格式（JSON/YAML 等价）。

场景结构（与前端场景生成页一致）：
    meta:        { name, version, author, created, description }
    sim:         { epoch, duration, step, seed, record }
    satellites:  [{ id, name, group, mass, fuel, payload:{type,state,power},
                    orbit:{ a(km), e, i, raan, argp, M0 } }]
    groundStations: [{ id, name, lat, lon }]
    events:      [{ t, type(机动/载荷/姿态/系统), target, action }]

校验规则与前端 scenario-store.js 保持一致，后端为最终权威。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import yaml

from simcore.timebase import parse_epoch

EARTH_R_KM = 6371.0
EVENT_TYPES = ("机动", "载荷", "姿态", "系统")


class ScenarioError(ValueError):
    """场景校验错误，message 面向用户可读。"""

    def __init__(self, errors: list[dict[str, str]]):
        self.errors = errors
        super().__init__("; ".join(f"[{e['loc']}] {e['msg']}" for e in errors))


@dataclass(frozen=True)
class OrbitDef:
    a: float        # 半长轴 (km)
    e: float
    i: float        # (°)
    raan: float     # (°)
    argp: float     # (°)
    m0: float       # 初始平近点角 (°)


@dataclass(frozen=True)
class SatelliteDef:
    sat_id: str
    name: str
    group: str
    mass: float     # (kg)
    fuel: float     # 燃料余量 (%)
    payload_type: str
    payload_state: str
    payload_power: float
    orbit: OrbitDef
    # 卫星原始定义（含可选 components 自定义组件链等扩展字段，供 assembly 使用）
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GroundStationDef:
    gs_id: str
    name: str
    lat: float
    lon: float


@dataclass(frozen=True)
class EventDef:
    t: float
    ev_type: str    # 机动 / 载荷 / 姿态 / 系统
    target: str
    action: str


@dataclass(frozen=True)
class Scenario:
    name: str
    version: str
    epoch_utc: str
    duration_s: float
    step_s: float
    seed: int
    record: bool
    description: str = ""
    satellites: tuple[SatelliteDef, ...] = ()
    ground_stations: tuple[GroundStationDef, ...] = ()
    events: tuple[EventDef, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def record_interval_s(self) -> float:
        """回放录制采样间隔：约 1500 帧覆盖全程，且不小于步长。"""
        return max(self.step_s, self.duration_s / 1500.0)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def validate_scenario(data: Any) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """返回 (errors, warnings)，规则与前端一致。"""
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    def err(loc: str, msg: str) -> None:
        errors.append({"loc": loc, "msg": msg})

    def warn(loc: str, msg: str) -> None:
        warnings.append({"loc": loc, "msg": msg})

    if not isinstance(data, dict):
        err("场景", "场景必须是 JSON/YAML 对象")
        return errors, warnings

    meta = data.get("meta") or {}
    if not isinstance(meta, dict) or not meta.get("name"):
        err("场景元信息", "场景名称不能为空")

    sim = data.get("sim")
    if not isinstance(sim, dict):
        err("仿真参数", "缺少仿真参数段")
        return errors, warnings
    epoch = sim.get("epoch")
    if not isinstance(epoch, str) or not epoch:
        err("仿真参数", "起始历元 epoch 必填（ISO8601 字符串）")
    else:
        try:
            parse_epoch(epoch)
        except ValueError:
            err("仿真参数", f"起始历元格式错误: {epoch}")
    duration = _num(sim.get("duration"))
    if duration is None or duration <= 0:
        err("仿真参数", "仿真时长必须大于 0")
    step = _num(sim.get("step"))
    if step is None or step <= 0:
        err("仿真参数", "仿真步长必须大于 0")
    elif step > 60:
        warn("仿真参数", "步长大于 60s，机动与预警事件可能漏检")
    seed = sim.get("seed")
    if isinstance(seed, bool) or not isinstance(seed, (int, float)) or int(seed) != seed:
        err("仿真参数", "随机种子必须为整数（实验可复现的关键）")

    sats = data.get("satellites") or []
    if not isinstance(sats, list):
        err("卫星列表", "satellites 必须是数组")
        sats = []
    ids: set[str] = set()
    for idx, st in enumerate(sats):
        if not isinstance(st, dict):
            err(f"卫星#{idx + 1}", "卫星必须是对象")
            continue
        loc = str(st.get("name") or st.get("id") or f"卫星#{idx + 1}")
        sid = st.get("id")
        if not sid:
            err(loc, "缺少卫星编号 id")
        elif sid in ids:
            err(loc, f"卫星编号重复：{sid}")
        else:
            ids.add(str(sid))
        if not st.get("name"):
            err(loc, "卫星名称不能为空")
        orbit = st.get("orbit") or {}
        a = _num(orbit.get("a"))
        ecc = _num(orbit.get("e"))
        inc = _num(orbit.get("i"))
        if a is None or a <= EARTH_R_KM + 100:
            err(loc, f"半长轴 a={orbit.get('a')} km 过小（须大于 {EARTH_R_KM + 100:.0f} km）")
        if ecc is None or not (0 <= ecc < 1):
            err(loc, "偏心率 e 须在 [0,1) 区间")
        elif a is not None and a * (1 - ecc) < EARTH_R_KM + 100:
            err(loc, "近地点高度低于 100 km，轨道将再入")
        if inc is None or not (0 <= inc <= 180):
            err(loc, "轨道倾角 i 须在 [0°,180°]")
        for key, label in (("raan", "raan"), ("argp", "argp"), ("M0", "M0")):
            val = _num(orbit.get(key))
            if val is None or not (0 <= val < 360):
                err(loc, f"{label} 须在 [0°,360°)")
        fuel = _num(st.get("fuel"))
        if fuel is None or not (0 <= fuel <= 100):
            err(loc, "燃料余量须在 0–100%")
        elif fuel < 20:
            warn(loc, "燃料余量低于 20%，机动类算法实验可能受限")
        mass = _num(st.get("mass"))
        if mass is None or mass <= 0:
            err(loc, "整星质量须大于 0")
        comps = st.get("components")
        if comps is not None:
            if not isinstance(comps, list):
                err(loc, "components 须为数组（缺省即使用标准组件链）")
            else:
                comp_names: set[str] = set()
                for cidx, comp in enumerate(comps):
                    cloc = f"{loc}.components#{cidx + 1}"
                    if not isinstance(comp, dict) or not comp.get("model"):
                        err(cloc, "组件须为对象且包含 model 字段（模型注册键）")
                        continue
                    cname = str(comp.get("name") or f"comp{cidx + 1}")
                    if cname in comp_names:
                        err(cloc, f"组件名重复：{cname}")
                    comp_names.add(cname)
    if len(sats) == 0:
        err("卫星列表", "场景至少需要 1 颗卫星")
    elif len(sats) > 50:
        warn("卫星列表", "实体超过 50，三维渲染与分析刷新率可能下降")

    stations = data.get("groundStations") or []
    if not isinstance(stations, list):
        err("地面站", "groundStations 必须是数组")
        stations = []
    for idx, gs in enumerate(stations):
        if not isinstance(gs, dict):
            err(f"地面站#{idx + 1}", "地面站必须是对象")
            continue
        loc = str(gs.get("name") or f"地面站#{idx + 1}")
        lat = _num(gs.get("lat"))
        lon = _num(gs.get("lon"))
        if lat is None or not (-90 <= lat <= 90):
            err(loc, "纬度须在 [-90°,90°]")
        if lon is None or not (-180 <= lon <= 180):
            err(loc, "经度须在 [-180°,180°]")

    events = data.get("events") or []
    if not isinstance(events, list):
        err("预设事件", "events 必须是数组")
        events = []
    for idx, ev in enumerate(events):
        loc = f"预设事件#{idx + 1}"
        if not isinstance(ev, dict):
            err(loc, "事件必须是对象")
            continue
        t = _num(ev.get("t"))
        if t is None or t < 0 or (duration is not None and t > duration):
            err(loc, f"触发时刻 t={ev.get('t')}s 超出仿真时长范围")
        target = ev.get("target")
        if target and str(target) not in ids:
            err(loc, f"目标 {target} 不存在于卫星列表")

    return errors, warnings


def scenario_from_dict(data: dict[str, Any]) -> Scenario:
    """从 dict 构建场景；校验失败抛出 ScenarioError（含全部错误项）。"""
    errors, _warnings = validate_scenario(data)
    if errors:
        raise ScenarioError(errors)

    meta = data["meta"]
    sim = data["sim"]
    satellites = tuple(
        SatelliteDef(
            sat_id=str(st["id"]),
            name=str(st["name"]),
            group=str(st.get("group") or ""),
            mass=float(st["mass"]),
            fuel=float(st["fuel"]),
            payload_type=str((st.get("payload") or {}).get("type") or "未知"),
            payload_state=str((st.get("payload") or {}).get("state") or "待机"),
            payload_power=float((st.get("payload") or {}).get("power") or 0),
            orbit=OrbitDef(
                a=float(st["orbit"]["a"]),
                e=float(st["orbit"]["e"]),
                i=float(st["orbit"]["i"]),
                raan=float(st["orbit"]["raan"]),
                argp=float(st["orbit"]["argp"]),
                m0=float(st["orbit"]["M0"]),
            ),
            raw=st,
        )
        for st in data["satellites"]
    )
    stations = tuple(
        GroundStationDef(
            gs_id=str(gs.get("id") or f"GS-{idx + 1:02d}"),
            name=str(gs.get("name") or f"地面站{idx + 1}"),
            lat=float(gs["lat"]),
            lon=float(gs["lon"]),
        )
        for idx, gs in enumerate(data.get("groundStations") or [])
    )
    events = tuple(
        sorted(
            (
                EventDef(
                    t=float(ev["t"]),
                    ev_type=str(ev.get("type") or "系统"),
                    target=str(ev.get("target") or ""),
                    action=str(ev.get("action") or ""),
                )
                for ev in data.get("events") or []
            ),
            key=lambda e: e.t,
        )
    )
    return Scenario(
        name=str(meta["name"]),
        version=str(meta.get("version") or "1.0.0"),
        description=str(meta.get("description") or ""),
        epoch_utc=str(sim["epoch"]),
        duration_s=float(sim["duration"]),
        step_s=float(sim["step"]),
        seed=int(sim["seed"]),
        record=bool(sim.get("record", True)),
        satellites=satellites,
        ground_stations=stations,
        events=events,
        raw=data,
    )


def load_scenario(text: str, fmt: str = "auto") -> Scenario:
    """从 JSON 或 YAML 文本加载场景。fmt: auto/json/yaml。"""
    stripped = text.strip()
    if not stripped:
        raise ScenarioError([{"loc": "场景", "msg": "场景内容为空"}])
    if fmt == "json" or (fmt == "auto" and stripped.startswith("{")):
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ScenarioError([{"loc": "场景", "msg": f"JSON 解析失败: {exc}"}]) from exc
    else:
        try:
            data = yaml.safe_load(stripped)
        except yaml.YAMLError as exc:
            raise ScenarioError([{"loc": "场景", "msg": f"YAML 解析失败: {exc}"}]) from exc
    return scenario_from_dict(data)
