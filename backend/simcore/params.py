"""七类参数结构（对应 AForce 规范表1）。

| 规范结构体          | Python 类       | 说明               |
|--------------------|-----------------|--------------------|
| CParamAttribute    | ParamAttribute  | 属性参数（初始化）  |
| CParamCtrInput     | ParamCtrInput   | 指控输入（指挥控制）|
| CParamDirInput     | ParamDirInput   | 导调输入（故障等）  |
| CParamRTInput      | ParamRTInput    | 实时输入（环境等）  |
| CParamRTOutput     | ParamRTOutput   | 实时输出（状态）    |
| CParamMROutput     | ParamMROutput   | 数据恢复（回放/恢复)|
| CParamKeyOutput    | ParamKeyOutput  | 关键输出（日志/裁决/事件）|

自定义参数部分统一用 dict 承载（对应规范中"模型开发方自定义参数"），
封套字段使用 frozen dataclass 保证不可变。规范要求所有 ID 用 long long，
Python 的 int 天然满足；本系统实体 ID 沿用场景文件中的字符串编号（如 "SAT-01"）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from simcore.bus import BusMessage


@dataclass(frozen=True)
class EntityInfo:
    """实体标准公共结构（属性/输出结构体的公共部分）。"""

    entity_id: str = ""
    model_id: int = 0
    name: str = ""
    group: str = ""        # 编组（功能分组，如 观测星组/非合作目标）
    faction: str = ""      # 阵营（红方/蓝方/中立，红蓝对抗用，与编组互不影响）


@dataclass(frozen=True)
class ParamAttribute:
    """属性参数结构体：实体标准公共结构 + 自定义数据。"""

    info: EntityInfo = field(default_factory=EntityInfo)
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParamCtrInput:
    """指控输入参数结构体：指控系统下发指令。"""

    entity_id: str = ""
    target_model: str = ""  # 目标组件名，空表示广播给实体内所有模型
    name: str = ""          # 指令名
    params: Mapping[str, Any] = field(default_factory=dict)
    time: float = 0.0       # 注入时刻（仿真秒）


@dataclass(frozen=True)
class ParamDirInput:
    """导调输入参数结构体：导调系统下发指令（故障注入等）。"""

    entity_id: str = ""
    target_model: str = ""
    name: str = ""
    params: Mapping[str, Any] = field(default_factory=dict)
    time: float = 0.0


@dataclass(frozen=True)
class ParamRTInput:
    """实时输入参数结构体：环境数据 + 实体内上游组件输出 + 订阅消息。"""

    env: Mapping[str, Any] = field(default_factory=dict)        # 全局环境（其他实体快照等）
    upstream: Mapping[str, Any] = field(default_factory=dict)   # 本实体内已推进组件的输出合并
    messages: tuple[BusMessage, ...] = ()                       # 订阅总线投递的消息（过滤后）


@dataclass(frozen=True)
class ParamRTOutput:
    """实时输出参数结构体：模型实时状态参数。"""

    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParamKeyOutput:
    """关键输出参数结构体：日志 + 裁决 + 关键事件。"""

    time: float = 0.0
    entity_id: str = ""
    source: str = ""        # 来源组件名
    level: str = "info"     # info / warning / critical
    event: str = ""         # 事件类型标识
    message: str = ""
    data: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ParamMROutput:
    """模型数据恢复结构体：模型过程恢复所需的全部内部状态。"""

    time: float = 0.0
    state: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    """sim_advance 的返回值：实时输出 + 关键输出 + 发布消息 + 恢复数据。"""

    rt_output: ParamRTOutput = field(default_factory=ParamRTOutput)
    key_outputs: tuple[ParamKeyOutput, ...] = ()
    messages: tuple[BusMessage, ...] = ()
    mr_output: ParamMROutput = field(default_factory=ParamMROutput)
