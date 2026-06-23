# backend/simcore/perception.py
"""感知图合并与战争迷雾视图（纯函数，供引擎/运行时/回放共用）。

裁决产出的 perception 形如 {faction: {entity_id: {pos_km, vel_kmps, source, age_s, observers}}}，
仅含非己方实体。faction_view 把「己方真值 + 已感知非己方」折叠为对外帧并移除 perception。

不可变约定（与全局确定性/性能契约一致）：本模块仅做浅拷贝构造新的外层容器，
**不修改入参**；嵌套载荷（pos_km/vel_kmps 等列表、实体快照）按「写一次、永不就地修改」
的全局约定与入参共享引用——这是热路径上规避 deepcopy 的有意取舍。下游消费者
（引擎并入 frozen Frame、运行时按阵营 faction_view 后立即序列化下发、回放端点
fog_recording 后即序列化返回）只读不改这些视图，故跨阵营/跨帧不会相互污染。
"""

from __future__ import annotations

from typing import Any

GOD_FACTIONS = {"", "全局", "中立"}   # 这些选择显示全局真值（中立方=全局）


def is_god(faction: str | None) -> bool:
    return faction is None or faction in GOD_FACTIONS


def merge_perception(parts: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """合并多份感知图：按 (faction, target) 取 age_s 最小者；并列时并集 observers。"""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for part in parts:
        if not part:
            continue
        for faction, targets in part.items():
            bucket = out.setdefault(faction, {})
            for tid, entry in targets.items():
                cur = bucket.get(tid)
                if cur is None or float(entry.get("age_s", 0.0)) < float(cur.get("age_s", 0.0)):
                    bucket[tid] = dict(entry)
                elif float(entry.get("age_s", 0.0)) == float(cur.get("age_s", 0.0)):
                    obs = list(dict.fromkeys(
                        list(cur.get("observers") or []) + list(entry.get("observers") or [])))
                    merged = dict(cur)
                    if obs:
                        merged["observers"] = obs
                    bucket[tid] = merged
    return out


def visible_entities(frame_dict: dict[str, Any], faction: str | None) -> dict[str, dict[str, Any]]:
    """阵营可见实体：god → 全部真值；阵营 → 己方真值 + 已感知非己方（揭示身份）。"""
    entities = frame_dict.get("entities", {}) or {}
    if is_god(faction):
        return dict(entities)
    perception = frame_dict.get("perception", {}) or {}
    seen = perception.get(faction, {}) or {}
    visible: dict[str, dict[str, Any]] = {}
    for eid, st in entities.items():
        if st.get("faction") == faction:
            visible[eid] = st
    for eid, pst in seen.items():
        base = entities.get(eid, {})
        merged = {"id": base.get("id", eid), "name": base.get("name", eid),
                  "faction": base.get("faction", ""), "group": base.get("group", "")}
        merged.update(pst)
        visible[eid] = merged
    return visible


def filter_events(events: list[dict[str, Any]] | None,
                  visible_ids: set[str]) -> list[dict[str, Any]]:
    """事件按 target 可见性过滤：target 为空或可见则放行。"""
    out: list[dict[str, Any]] = []
    for ev in events or []:
        tgt = ev.get("target")
        if not tgt or tgt in visible_ids:
            out.append(ev)
    return out


def faction_view(frame_dict: dict[str, Any], faction: str | None) -> dict[str, Any]:
    """产出阵营迷雾帧：折叠可见实体、过滤帧内事件、移除 perception 字段。"""
    vis = visible_entities(frame_dict, faction)
    out = dict(frame_dict)
    out["entities"] = vis
    out["events"] = filter_events(frame_dict.get("events", []), set(vis))
    out.pop("perception", None)
    return out


def fog_recording(rec: dict[str, Any], faction: str | None) -> dict[str, Any]:
    """回放迷雾：逐帧 faction_view；事件按「曾可见」集合过滤（己方∪任意帧已感知目标）。"""
    if is_god(faction):
        return rec
    frames = rec.get("frames", []) or []
    ever: set[str] = set()
    for f in frames:
        for eid, st in (f.get("entities") or {}).items():
            if st.get("faction") == faction:
                ever.add(eid)
        for tid in (f.get("perception", {}) or {}).get(faction, {}):
            ever.add(tid)
    fogged_frames = [faction_view(f, faction) for f in frames]
    fogged_events = [ev for ev in rec.get("events", []) or []
                     if not ev.get("target") or ev.get("target") in ever]
    return {**rec, "frames": fogged_frames, "events": fogged_events}
