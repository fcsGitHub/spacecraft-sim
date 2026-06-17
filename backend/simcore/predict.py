"""预推演：克隆当前引擎状态前向空跑，得到各实体未来航迹。

预测沙箱与实时引擎共享同一套实体装配与动力学（J2 / 推进 / 姿态 / 载荷
及任意自定义组件），并携带尚未触发的预约指令，因此预测与本次推演一致：
- 以引擎步长推进时，预测前几步与真实继续推进逐点一致；
- 包含 J2 摄动、在途点火残量、未来预约机动。

超长时长按步数上限自适应放大预测步长（orbits.propagate 内部仍按 ≤10s
子步，轨道积分精度不受影响），并在结果中回报 step_used_s，便于前端标注。

全程只读实时引擎（snapshot_mr / rng.getstate / pending_commands），
不改动其任何状态。线程化调用时请在主线程先取状态再交线程，避免与实时推进竞争。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from simcore.engine import Frame, SimulationEngine

MAX_PREDICT_STEPS = 8000   # 内部步数上限，约束超长时长的计算量
TARGET_SAMPLES = 600       # 默认采样点数（未显式指定 sample_step_s 时）


@dataclass(frozen=True)
class PredictionResult:
    """预推演结果：各实体未来航迹采样（ECI，km / km·s⁻¹）。"""

    t0: float                                   # 预测起点（绝对仿真秒）
    horizon_s: float                            # 预测时长
    step_used_s: float                          # 实际内部步长（超长时长时大于引擎步长）
    times: list[float]                          # 采样时刻（绝对仿真秒，含起点）
    tracks: dict[str, list[dict[str, Any]]]     # id -> [{pos_km, vel_kmps}, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "t0": round(self.t0, 3),
            "horizon_s": self.horizon_s,
            "step_used_s": round(self.step_used_s, 4),
            "times": [round(t, 3) for t in self.times],
            "tracks": self.tracks,
        }


def capture_state(engine: SimulationEngine) -> dict[str, Any]:
    """主线程同步取出克隆所需的引擎状态（cheap），避免与实时推进竞争。

    线程化预测时，先在主线程调用本函数，再把返回的 bundle 交给 run_prediction。
    """
    return {
        "scenario": engine.scenario,
        "mr": engine.snapshot_mr(),
        "rng": engine.rng.getstate(),
        "pending": engine.pending_commands(),
        "alert_km": engine.alert_threshold_km,
        "step_s": engine.step_s,
        "ids": [info["id"] for info in engine.entity_infos()],
    }


def _build_sandbox(captured: dict[str, Any]) -> SimulationEngine:
    """从捕获的状态 bundle 克隆沙箱引擎（动力学一致，时刻对齐当前）。"""
    sandbox = SimulationEngine(captured["scenario"])
    sandbox.init()
    sandbox.restore_mr(captured["mr"])              # 还原全组件内部状态 + 时钟
    sandbox.rng.setstate(captured["rng"])           # 对齐随机流（自定义模型可能用到）
    sandbox.alert_threshold_km = captured["alert_km"]
    sandbox.step(0.0)                               # 以恢复后的状态刷新 last_frame，不推进时钟
    for cmd in captured["pending"]:                 # 携带未触发的预约指令
        sandbox.schedule_command(cmd)
    return sandbox


def _sample(frame: Frame, ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for eid in ids:
        st = frame.entities.get(eid) or {}
        out[eid] = {
            "pos_km": list(st.get("pos_km") or []),
            "vel_kmps": list(st.get("vel_kmps") or []),
        }
    return out


def run_prediction(
    captured: dict[str, Any], horizon_s: float, sample_step_s: float | None = None
) -> PredictionResult:
    """基于 capture_state 的 bundle 前向预测（可安全置于工作线程执行）。

    sample_step_s 缺省时自动取 ~TARGET_SAMPLES 个采样点（且不小于内部步长）。
    """
    if horizon_s <= 0:
        raise ValueError(f"预推演时长须为正: {horizon_s}")

    step = float(captured["step_s"])
    if math.ceil(horizon_s / step) > MAX_PREDICT_STEPS:
        step = horizon_s / MAX_PREDICT_STEPS    # 自适应放大，约束总步数
    if sample_step_s is None:
        sample_step_s = max(step, horizon_s / TARGET_SAMPLES)
    sample_every = max(1, round(sample_step_s / step))

    sandbox = _build_sandbox(captured)
    ids: list[str] = list(captured["ids"])
    t0 = sandbox.clock.t
    end_t = t0 + horizon_s

    times: list[float] = [t0]
    tracks: dict[str, list[dict[str, Any]]] = {eid: [] for eid in ids}
    initial = _sample(sandbox.last_frame, ids) if sandbox.last_frame else {}
    for eid in ids:
        tracks[eid].append(initial.get(eid, {"pos_km": [], "vel_kmps": []}))

    i = 0
    while sandbox.clock.t < end_t - 1e-9:
        dt = min(step, end_t - sandbox.clock.t)
        frame = sandbox.step(dt)
        i += 1
        is_last = sandbox.clock.t >= end_t - 1e-9
        if i % sample_every == 0 or is_last:
            sampled = _sample(frame, ids)
            times.append(sandbox.clock.t)
            for eid in ids:
                tracks[eid].append(sampled[eid])

    return PredictionResult(
        t0=t0, horizon_s=horizon_s, step_used_s=step, times=times, tracks=tracks
    )


def predict_tracks(
    engine: SimulationEngine, horizon_s: float, sample_step_s: float | None = None
) -> PredictionResult:
    """同步便捷封装：捕获引擎状态并前向预测（脚本/测试用）。

    服务端的异步路径应改用 capture_state（主线程）+ run_prediction（工作线程）。
    """
    return run_prediction(capture_state(engine), horizon_s, sample_step_s)
