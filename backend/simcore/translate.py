"""前端指令模板 / 场景预设事件 -> 引擎计划指令的翻译层。

前端指令模板（态势页指令注入选项卡）：
    轨道机动 {dv (m/s), dir (切向/法向/径向)}
    载荷控制 {act (开机/关机/单次成像/持续侦收)}
    姿态调整 {att (对地定向/对日定向/惯性指向/目标跟瞄)}
    编队保持 {ref (参考星id), dist (km)}

场景预设事件（场景生成页 events 表）按类型 + 动作文本解析：
    机动: 从文本提取 "Δv=X m/s" 与方向（切向/法向/径向，默认切向）
    载荷: 文本含 关机/关闭 -> 关机；成像 -> 单次成像；侦收 -> 持续侦收；否则 开机
    姿态: 文本含已知姿态模式则取之，否则 对地定向
    系统: 文本含 失效/故障 -> 导调故障注入，否则仅记录事件
"""

from __future__ import annotations

import re
from typing import Any

from simcore.engine import ScheduledCommand
from simcore.scenario import EventDef

ATTITUDE_MODES = ("对地定向", "对日定向", "惯性指向", "目标跟瞄", "交会对接姿态")

_DV_PATTERN = re.compile(r"Δv\s*=?\s*([\d.]+)")


class TranslateError(ValueError):
    pass


def command_from_template(
    tpl: str, target: str, params: dict[str, Any], t: float, source: str = "command"
) -> ScheduledCommand:
    """前端指令模板 -> 计划指令。未知模板抛 TranslateError。"""
    if tpl == "轨道机动":
        dv = float(params.get("dv") or 0)
        direction = str(params.get("dir") or "切向")
        if direction not in ("切向", "法向", "径向"):
            raise TranslateError(f"未知机动方向: {direction}")
        return ScheduledCommand(
            t=t, entity_id=target, channel="ctr", name="maneuver", target_model="thruster",
            params={"dv_mps": dv, "dir": direction},
            label=f"轨道机动 Δv={dv} m/s {direction}", ev_type="机动", source=source,
        )
    if tpl == "载荷控制":
        act = str(params.get("act") or "开机")
        return ScheduledCommand(
            t=t, entity_id=target, channel="ctr", name="payload_ctrl", target_model="payload",
            params={"act": act}, label=f"载荷{act}", ev_type="载荷", source=source,
        )
    if tpl == "姿态调整":
        att = str(params.get("att") or "对地定向")
        return ScheduledCommand(
            t=t, entity_id=target, channel="ctr", name="set_attitude", target_model="attitude",
            params={"mode": att}, label=f"姿态调整 → {att}", ev_type="姿态", source=source,
        )
    if tpl == "编队保持":
        ref = str(params.get("ref") or "")
        dist = float(params.get("dist") or 50)
        return ScheduledCommand(
            t=t, entity_id=target, channel="ctr", name="formation_keep", target_model="thruster",
            params={"ref_id": ref, "dist_km": dist},
            label=f"编队保持 ref={ref} {dist}km", ev_type="指令", source=source,
        )
    raise TranslateError(f"未知指令模板: {tpl}")


def command_from_event(ev: EventDef) -> ScheduledCommand | None:
    """场景预设事件 -> 计划指令；纯记录型事件返回 None。"""
    text = ev.action or ""
    label = f"{ev.target} {text}".strip()

    if ev.ev_type == "机动":
        match = _DV_PATTERN.search(text)
        dv = float(match.group(1)) if match else 1.5
        direction = "法向" if "法向" in text else "径向" if "径向" in text else "切向"
        return ScheduledCommand(
            t=ev.t, entity_id=ev.target, channel="ctr", name="maneuver", target_model="thruster",
            params={"dv_mps": dv, "dir": direction}, label=label, ev_type="机动", source="event",
        )
    if ev.ev_type == "载荷":
        if "关机" in text or "关闭" in text:
            act = "关机"
        elif "成像" in text:
            act = "单次成像"
        elif "侦收" in text:
            act = "持续侦收"
        else:
            act = "开机"
        return ScheduledCommand(
            t=ev.t, entity_id=ev.target, channel="ctr", name="payload_ctrl", target_model="payload",
            params={"act": act}, label=label, ev_type="载荷", source="event",
        )
    if ev.ev_type == "姿态":
        mode = next((m for m in ATTITUDE_MODES if m in text), "对地定向")
        return ScheduledCommand(
            t=ev.t, entity_id=ev.target, channel="ctr", name="set_attitude", target_model="attitude",
            params={"mode": mode}, label=label, ev_type="姿态", source="event",
        )
    if ev.ev_type == "系统":
        if "失效" in text or "故障" in text:
            return ScheduledCommand(
                t=ev.t, entity_id=ev.target, channel="dir", name="fault", target_model="",
                params={"desc": text}, label=label, ev_type="系统", source="event",
            )
        return ScheduledCommand(
            t=ev.t, entity_id=ev.target, channel="ctr", name="log", target_model="payload",
            params={"desc": text}, label=label, ev_type="系统", source="event",
        )
    return None
