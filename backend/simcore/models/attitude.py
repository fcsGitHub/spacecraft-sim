"""简化姿态模型：姿态模式管理 + 确定性姿态偏差遥测。

姿态偏差用种子化的正弦叠加生成（与回放逐位一致），模式切换后产生
按指数衰减的瞬态偏差，便于在遥测曲线上观察指令效果。

指控指令：set_attitude {mode}
导调指令：fault {desc} 姿控故障（偏差放大 5 倍）
实时输出：att_mode、att_dev_deg
"""

from __future__ import annotations

import math

from simcore.model import Array6, AtomicModel, SimContext
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
from simcore.registry import register_model

ATTITUDE_MODES = ("对地定向", "对日定向", "惯性指向", "目标跟瞄", "交会对接姿态")
TRANSIENT_DEV_DEG = 6.0     # 模式切换瞬态幅值
TRANSIENT_TAU_S = 60.0      # 瞬态衰减时间常数


def _noise(seed: float, t: float, freq: float) -> float:
    """确定性噪声（与前端原型同形）。"""
    return (
        math.sin(t * freq + seed * 0.7) * 0.6
        + math.sin(t * freq * 2.7 + seed * 1.3) * 0.3
        + math.sin(t * freq * 7.1 + seed * 2.9) * 0.1
    )


@register_model
class SimpleAttitudeModel(AtomicModel):
    model_type = "aocs.simple"
    display_name = "简化姿态控制"
    category = "aocs"
    description = "姿态模式管理与确定性姿态偏差遥测，支持姿控故障注入。"

    attribute_schema = {
        "mode": {
            "type": "select",
            "options": list(ATTITUDE_MODES),
            "default": "对地定向",
            "desc": "初始姿态模式",
        },
    }
    ctr_commands = {
        "set_attitude": {
            "desc": "姿态调整",
            "params": {
                "mode": {"type": "select", "options": list(ATTITUDE_MODES), "desc": "目标姿态"},
            },
        },
    }
    dir_commands = {
        "fault": {"desc": "姿控故障（偏差放大）", "params": {"desc": {"type": "string", "desc": "故障说明"}}},
    }

    def __init__(self) -> None:
        super().__init__()
        self._mode = "对地定向"
        self._seed = 0.0
        self._switch_t = -1e9  # 上次模式切换时刻
        self._failed = False
        self._t = 0.0

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        data = {**self.default_attributes(), **dict(attribute.data)}
        mode = str(data.get("mode") or "对地定向")
        self._mode = mode if mode in ATTITUDE_MODES else "对地定向"
        self._seed = (ctx.engine.scenario.seed % 1000) + len(ctx.entity_id) * 13
        self._switch_t = -1e9
        self._failed = False
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        if ctr_in.name != "set_attitude":
            return 0
        mode = str(ctr_in.params.get("mode") or "")
        if mode not in ATTITUDE_MODES:
            return 1
        if mode != self._mode:
            self._mode = mode
            self._switch_t = ctr_in.time
        return 0

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        if dir_in.name == "fault":
            self._failed = True
        return 0

    def sim_advance(
        self, ctx: SimContext, bjt: Array6, utc: Array6, step: float, rt_in: ParamRTInput
    ) -> StepResult:
        sim_t = ctx.sim_time + step
        self._t = sim_t
        dev = _noise(self._seed, sim_t, 0.004) * 1.8
        elapsed = sim_t - self._switch_t
        if 0 <= elapsed < TRANSIENT_TAU_S * 5:
            dev += TRANSIENT_DEV_DEG * math.exp(-elapsed / TRANSIENT_TAU_S)
        if self._failed:
            dev *= 5.0
        rt_output = ParamRTOutput(data={
            "att_mode": self._mode,
            "att_dev_deg": round(dev, 4),
            "aocs_failed": self._failed,
        })
        mr = ParamMROutput(time=sim_t, state={
            "mode": self._mode, "switch_t": self._switch_t, "failed": self._failed,
        })
        return StepResult(rt_output=rt_output, key_outputs=(), mr_output=mr)

    def sim_restore(self, mr: ParamMROutput) -> int:
        state = dict(mr.state)
        self._mode = str(state.get("mode", self._mode))
        self._switch_t = float(state.get("switch_t", -1e9))
        self._failed = bool(state.get("failed", False))
        return 0
