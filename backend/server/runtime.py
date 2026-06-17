"""仿真运行时：异步推进循环、倍速调度、异步指令注入、WS 广播、录制。

引擎是同步确定性的；本模块负责把它接入实时世界：
- 固定节拍（TICK_S）推进若干仿真步（步数 = 倍速 × 节拍 / 步长，含小数累积）
- 指令经 asyncio 队列在两步之间注入（对应规范的异步指控/导调输入）
- 帧与事件按节拍广播给全部 WebSocket 客户端与外发连接器
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Coroutine
from typing import Any

from simcore import (
    Recorder,
    SimulationEngine,
    TranslateError,
    capture_state,
    command_from_event,
    command_from_template,
    run_prediction,
    scenario_from_dict,
)

logger = logging.getLogger("scsim.runtime")

TICK_S = 0.05                # 推进节拍（实时秒）
MAX_STEPS_PER_TICK = 600     # 单节拍最大步数（防止卡顿后追赶雪崩）
BROADCAST_MIN_INTERVAL = 1 / 15  # 帧广播最高 15 Hz
MAX_PREDICT_HORIZON_S = 7 * 86400  # 预推演时长上限（7 天）

PushHook = Callable[[dict[str, Any]], Coroutine[Any, Any, None]]


class RuntimeError_(Exception):
    """运行时操作错误（面向 API 的可读消息）。"""


class SimulationRunner:
    """单实例仿真运行时。"""

    def __init__(self, recordings_dir: str):
        self.recordings_dir = recordings_dir
        self.state = "idle"  # idle / paused / running / finished
        self.speed = 60.0
        self.engine: SimulationEngine | None = None
        self.recorder: Recorder | None = None
        self.scenario_dict: dict[str, Any] | None = None
        self.user_commands: list[dict[str, Any]] = []
        self.last_recording_id: str | None = None
        self._clients: set[Any] = set()
        self._task: asyncio.Task[None] | None = None
        self._step_debt = 0.0
        self._pending_events: list[dict[str, Any]] = []
        self._last_broadcast = 0.0
        self._push_hook: PushHook | None = None

    # ---- 装载与生命周期 ----

    def load(self, scenario_dict: dict[str, Any]) -> None:
        """从场景字典构建引擎（校验失败抛 ScenarioError）。"""
        scenario = scenario_from_dict(scenario_dict)
        self.stop_loop()
        engine = SimulationEngine(scenario)
        engine.init()
        for ev in scenario.events:
            cmd = command_from_event(ev)
            if cmd is not None:
                engine.schedule_command(cmd)
        self.engine = engine
        self.scenario_dict = scenario_dict
        self.recorder = Recorder(scenario=scenario) if scenario.record else None
        if self.recorder and engine.last_frame:
            self.recorder.on_frame(engine.last_frame)
        self.user_commands = []
        self._pending_events = []
        self._step_debt = 0.0
        self.state = "paused"
        logger.info("场景已装载: %s（%d 实体）", scenario.name, len(scenario.satellites))

    def reset(self) -> None:
        """复位到 T+0：同场景重建引擎（同种子同指令序列可逐位复现）。"""
        if self.scenario_dict is None:
            raise RuntimeError_("尚未装载场景")
        self.load(self.scenario_dict)

    def start(self) -> None:
        if self.engine is None:
            raise RuntimeError_("尚未装载场景，无法开始")
        if self.state == "finished":
            self.reset()
        self.state = "running"
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run_loop())

    def pause(self) -> None:
        if self.state == "running":
            self.state = "paused"

    def stop_loop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def set_speed(self, speed: float) -> None:
        if not 0 < speed <= 3600:
            raise RuntimeError_(f"倍速须在 (0, 3600]，当前 {speed}")
        self.speed = speed

    def set_alert_threshold(self, km: float) -> None:
        if self.engine is None:
            raise RuntimeError_("尚未装载场景")
        if not 0 < km <= 100000:
            raise RuntimeError_(f"预警门限须在 (0, 100000] km，当前 {km}")
        self.engine.alert_threshold_km = km

    # ---- 推进 ----

    async def step_once(self, dt: float = 10.0) -> None:
        """单步推进 dt 仿真秒（暂停状态下使用）。"""
        engine = self._require_engine()
        if self.state == "running":
            raise RuntimeError_("运行中无法单步推进，请先暂停")
        if not 0 < dt <= 3600:
            raise RuntimeError_(f"单步时长须在 (0, 3600] s，当前 {dt}")
        steps = max(1, round(dt / engine.step_s))
        for _ in range(steps):
            if engine.finished:
                break
            self._advance_one_step()
        if engine.finished:
            self._finish()
        await self._broadcast_frame(force=True)
        await self.broadcast_status()

    def _advance_one_step(self) -> None:
        engine = self._require_engine()
        frame = engine.step()
        if self.recorder:
            self.recorder.on_frame(frame)
        if frame.events:
            self._pending_events.extend(frame.to_dict()["events"])

    async def _run_loop(self) -> None:
        await self.broadcast_status()
        last = time.monotonic()
        try:
            while self.state == "running":
                now = time.monotonic()
                real_dt = min(now - last, 0.5)
                last = now
                engine = self._require_engine()
                self._step_debt += self.speed * real_dt / engine.step_s
                steps = min(int(self._step_debt), MAX_STEPS_PER_TICK)
                self._step_debt -= steps
                for _ in range(steps):
                    if engine.finished:
                        break
                    self._advance_one_step()
                if engine.finished:
                    self._finish()
                    await self._broadcast_frame(force=True)
                    await self.broadcast_status()
                    break
                await self._broadcast_frame()
                await asyncio.sleep(TICK_S)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("仿真推进循环异常终止")
            self.state = "paused"
            await self.broadcast_status()

    def _finish(self) -> None:
        engine = self._require_engine()
        engine.end()
        self.state = "finished"
        if self.recorder:
            try:
                path = self.recorder.save(self.recordings_dir)
                self.last_recording_id = self.recorder.run_id
                logger.info("回放录制已保存: %s", path)
            except OSError:
                logger.exception("录制保存失败")

    # ---- 指令注入 ----

    async def inject_command(self, tpl: str, target: str, params: dict[str, Any],
                             when: str, delay: float) -> dict[str, Any]:
        engine = self._require_engine()
        t = engine.clock.t if when == "now" else engine.clock.t + max(0.0, delay)
        if t > engine.scenario.duration_s:
            raise RuntimeError_("执行时刻超出仿真时长")
        try:
            cmd = command_from_template(tpl, target, params, t=round(t, 3))
        except (TranslateError, ValueError, TypeError) as exc:
            raise RuntimeError_(f"指令参数错误: {exc}") from exc
        if when == "now":
            record = engine.inject_now(cmd)
            self._pending_events.append({
                "t": record.time, "target": record.entity_id, "source": record.source,
                "level": record.level, "type": record.event, "text": record.message,
                "data": dict(record.data),
            })
            await self._broadcast_frame(force=True)
        else:
            engine.schedule_command(cmd)
        entry = {"tpl": tpl, "target": target, "params": params,
                 "t": cmd.t, "label": cmd.label}
        self.user_commands.append(entry)
        return entry

    def command_list(self) -> list[dict[str, Any]]:
        t = self.engine.clock.t if self.engine else 0.0
        return [{**c, "fired": c["t"] <= t} for c in self.user_commands]

    # ---- 预推演 ----

    async def predict(self, horizon_s: float, sample_step_s: float | None = None
                      ) -> dict[str, Any]:
        """前向预推演当前态势：动力学与本次推演一致，含未触发的预约指令。

        在主线程同步捕获引擎状态后，于工作线程跑前向推演，避免阻塞事件循环
        与实时推进竞争。
        """
        engine = self._require_engine()
        if not 0 < horizon_s <= MAX_PREDICT_HORIZON_S:
            raise RuntimeError_(
                f"预推演时长须在 (0, {MAX_PREDICT_HORIZON_S}] s，当前 {horizon_s}"
            )
        captured = capture_state(engine)  # 主线程同步取状态（cheap）
        result = await asyncio.to_thread(run_prediction, captured, horizon_s, sample_step_s)
        return result.to_dict()

    # ---- 广播 ----

    def set_push_hook(self, hook: PushHook) -> None:
        """外发连接器钩子：每次帧广播时回调。"""
        self._push_hook = hook

    def attach(self, ws: Any) -> None:
        self._clients.add(ws)

    def detach(self, ws: Any) -> None:
        self._clients.discard(ws)

    def status_payload(self) -> dict[str, Any]:
        engine = self.engine
        scenario = engine.scenario if engine else None
        return {
            "state": self.state,
            "t": engine.clock.t if engine else 0.0,
            "duration": scenario.duration_s if scenario else 0.0,
            "step": scenario.step_s if scenario else 1.0,
            "speed": self.speed,
            "scenario_name": scenario.name if scenario else None,
            "scenario_version": scenario.version if scenario else None,
            "seed": scenario.seed if scenario else None,
            "record": scenario.record if scenario else False,
            "alert_threshold_km": engine.alert_threshold_km if engine else 100.0,
            "entity_count": len(scenario.satellites) if scenario else 0,
            "last_recording_id": self.last_recording_id,
        }

    async def broadcast_status(self) -> None:
        await self._send_all({"type": "status", "data": self.status_payload()})

    async def broadcast_frame_now(self) -> None:
        """立即广播当前帧（装载/复位后让客户端同步 T+0 状态）。"""
        await self._broadcast_frame(force=True)

    async def _broadcast_frame(self, force: bool = False) -> None:
        engine = self.engine
        if engine is None or engine.last_frame is None:
            return
        now = time.monotonic()
        if not force and now - self._last_broadcast < BROADCAST_MIN_INTERVAL:
            return
        self._last_broadcast = now
        frame_dict = engine.last_frame.to_dict()
        message = {
            "type": "frame",
            "data": {**frame_dict, "events": []},
            "events": self._pending_events,
            "state": self.state,
        }
        self._pending_events = []
        await self._send_all(message)
        if self._push_hook is not None:
            try:
                await self._push_hook(message["data"])
            except Exception:
                logger.exception("外发推送失败")

    async def send_snapshot(self, ws: Any) -> None:
        """新客户端接入：补发状态与最新帧。"""
        await ws.send_json({"type": "status", "data": self.status_payload()})
        if self.engine and self.engine.last_frame:
            frame_dict = self.engine.last_frame.to_dict()
            await ws.send_json({"type": "frame", "data": {**frame_dict, "events": []},
                                "events": [], "state": self.state})

    async def _send_all(self, message: dict[str, Any]) -> None:
        if not self._clients:
            return
        text = json.dumps(message, ensure_ascii=False)  # 序列化一次，N 客户端复用
        dead: list[Any] = []
        for ws in self._clients:
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self._clients.discard(ws)

    # ---- 工具 ----

    def _require_engine(self) -> SimulationEngine:
        if self.engine is None:
            raise RuntimeError_("尚未装载场景")
        return self.engine
