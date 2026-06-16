"""simcore — 空间飞行器仿真引擎核心包。

参照《AForce原子模型仿真建模规范V3.0》的 Python 实现：
- 原子模型五接口：sim_init / sim_ctr_response / sim_dir_response / sim_advance / sim_end
- 七类参数结构：属性 / 指控输入 / 导调输入 / 实时输入 / 实时输出 / 数据恢复 / 关键输出
- 模型注册表 + 自动发现，便于研究人员扩展自定义模型

本包不依赖任何 Web 框架，可独立用于脚本化研究：

    from simcore import load_scenario, SimulationEngine, discover_builtin_models
    discover_builtin_models()
    engine = SimulationEngine(load_scenario(open("场景.json", encoding="utf-8").read()))
    engine.init()
    while not engine.finished:
        frame = engine.step()
"""

from simcore.params import (
    EntityInfo,
    ParamAttribute,
    ParamCtrInput,
    ParamDirInput,
    ParamRTInput,
    ParamRTOutput,
    ParamKeyOutput,
    ParamMROutput,
    StepResult,
)
from simcore.model import AtomicModel, SimContext
from simcore.registry import (
    register_model,
    get_model_class,
    list_models,
    discover_builtin_models,
    load_models_from_dir,
)
from simcore.scenario import (
    Scenario,
    ScenarioError,
    load_scenario,
    scenario_from_dict,
    validate_scenario,
)
from simcore.engine import Frame, ScheduledCommand, SimulationEngine
from simcore.translate import TranslateError, command_from_event, command_from_template
from simcore.recorder import Recorder, delete_recording, list_recordings, load_recording

__all__ = [
    "EntityInfo",
    "ParamAttribute",
    "ParamCtrInput",
    "ParamDirInput",
    "ParamRTInput",
    "ParamRTOutput",
    "ParamKeyOutput",
    "ParamMROutput",
    "StepResult",
    "AtomicModel",
    "SimContext",
    "register_model",
    "get_model_class",
    "list_models",
    "discover_builtin_models",
    "load_models_from_dir",
    "Scenario",
    "ScenarioError",
    "load_scenario",
    "scenario_from_dict",
    "validate_scenario",
    "Frame",
    "ScheduledCommand",
    "SimulationEngine",
    "TranslateError",
    "command_from_event",
    "command_from_template",
    "Recorder",
    "delete_recording",
    "list_recordings",
    "load_recording",
]
