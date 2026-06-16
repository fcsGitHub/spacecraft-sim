"""原子模型基类（对应 AForce 规范"接口规范"一节）。

研究人员扩展模型只需三步：
1. 继承 AtomicModel，实现 sim_advance（其余接口按需覆写）；
2. 类属性填写 model_type / attribute_schema / ctr_commands / dir_commands；
3. 用 @register_model 注册（放入 simcore/models/ 或通过 extra_model_dirs 加载）。

接口对照（C++ -> Python）：
    SimInit         -> sim_init(ctx, bjt, utc, attribute)
    SimCtrResponse  -> sim_ctr_response(ctr_in)
    SimDirResponse  -> sim_dir_response(dir_in)
    SimAdvance      -> sim_advance(ctx, bjt, utc, step, rt_in) -> StepResult
    SimEnd          -> sim_end(ctx, bjt, utc, step)
    （扩展）数据恢复 -> sim_restore(mr)，用于回放断点恢复
返回值约定与规范一致：0 表示正常，非 0 表示异常。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from simcore.params import (
    ParamAttribute,
    ParamCtrInput,
    ParamDirInput,
    ParamMROutput,
    ParamRTInput,
    StepResult,
)

if TYPE_CHECKING:
    from simcore.engine import SimulationEngine

Array6 = tuple[float, float, float, float, float, float]


@dataclass(frozen=True)
class SimContext:
    """引擎公共指针 pShare 的 Python 对应：向模型暴露受控的引擎信息。"""

    engine: "SimulationEngine"
    entity_id: str = ""
    component: str = ""

    @property
    def sim_time(self) -> float:
        return self.engine.clock.t

    def entity_snapshot(self, entity_id: str) -> dict[str, Any] | None:
        """查询其他实体上一步的状态快照（避免同步耦合）。"""
        return self.engine.last_entity_states.get(entity_id)


class AtomicModel(ABC):
    """原子模型基类。子类必须定义 model_type 并实现 sim_advance。"""

    # ---- 模型元数据（供注册表与前端表单自动生成使用）----
    model_type: str = ""          # 注册键，如 "orbit.j2"
    display_name: str = ""        # 中文显示名
    category: str = "general"     # orbit / propulsion / sensor / payload ...
    description: str = ""
    # 属性参数说明：{参数名: {"type","unit","default","desc"}}
    attribute_schema: dict[str, dict[str, Any]] = {}
    # 支持的指控指令：{指令名: {"desc","params": {参数名: {...}}}}
    ctr_commands: dict[str, dict[str, Any]] = {}
    # 支持的导调指令（故障注入等）
    dir_commands: dict[str, dict[str, Any]] = {}

    def __init__(self) -> None:
        self.attribute: ParamAttribute = ParamAttribute()

    # ---- 五大标准接口 ----

    def sim_init(self, ctx: SimContext, bjt: Array6, utc: Array6, attribute: ParamAttribute) -> int:
        """仿真初始化：保存属性参数。子类覆写时应先调用 super().sim_init(...)。"""
        self.attribute = attribute
        return 0

    def sim_ctr_response(self, ctr_in: ParamCtrInput) -> int:
        """指控输入响应。默认忽略未知指令（返回 0）。"""
        return 0

    def sim_dir_response(self, dir_in: ParamDirInput) -> int:
        """导调输入响应（故障注入等）。默认忽略。"""
        return 0

    @abstractmethod
    def sim_advance(
        self,
        ctx: SimContext,
        bjt: Array6,
        utc: Array6,
        step: float,
        rt_in: ParamRTInput,
    ) -> StepResult:
        """仿真推进：每步调用一次，返回实时输出/关键输出/恢复数据。"""

    def sim_end(self, ctx: SimContext, bjt: Array6, utc: Array6, step: float) -> int:
        """仿真结束：释放资源（一般模型无需处理）。"""
        return 0

    # ---- 数据恢复扩展接口 ----

    def sim_restore(self, mr: ParamMROutput) -> int:
        """从恢复数据还原模型内部状态（用于断点恢复/回放接续）。"""
        return 0

    # ---- 工具 ----

    @classmethod
    def default_attributes(cls) -> dict[str, Any]:
        return {key: spec.get("default") for key, spec in cls.attribute_schema.items()}

    @classmethod
    def metadata(cls) -> dict[str, Any]:
        """模型说明（对应规范"模型说明文件"），供 /api/models 与场景编辑器使用。"""
        return {
            "model_type": cls.model_type,
            "display_name": cls.display_name or cls.model_type,
            "category": cls.category,
            "description": cls.description,
            "attribute_schema": cls.attribute_schema,
            "ctr_commands": cls.ctr_commands,
            "dir_commands": cls.dir_commands,
        }
