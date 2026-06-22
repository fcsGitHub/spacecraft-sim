"""模型注册表：研究人员扩展模型的入口。

用法：
    @register_model
    class MyModel(AtomicModel):
        model_type = "my.model"
        ...

内置模型放在 simcore/models/ 下，由 discover_builtin_models() 自动导入；
外部模型目录可通过 load_models_from_dir(path) 动态加载（外接系统/插件场景）。
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import pkgutil
import sys
from pathlib import Path
from typing import Any, TypeVar

from simcore.model import SimModel

_REGISTRY: dict[str, type[SimModel]] = {}

TModel = TypeVar("TModel", bound=type[SimModel])


class RegistryError(Exception):
    pass


def register_model(cls: TModel) -> TModel:
    """类装饰器：按 model_type 注册仿真模型（原子/组合/裁决均可）。"""
    if not cls.model_type:
        raise RegistryError(f"{cls.__name__} 缺少 model_type，无法注册")
    existing = _REGISTRY.get(cls.model_type)
    if existing is not None and existing is not cls:
        raise RegistryError(f"model_type 冲突: {cls.model_type} 已被 {existing.__name__} 注册")
    _REGISTRY[cls.model_type] = cls
    return cls


def get_model_class(model_type: str) -> type[SimModel]:
    cls = _REGISTRY.get(model_type)
    if cls is None:
        known = ", ".join(sorted(_REGISTRY)) or "(空)"
        raise RegistryError(f"未注册的模型类型: {model_type}，已注册: {known}")
    return cls


def list_models() -> list[dict[str, Any]]:
    """全部已注册模型的元数据（供前端动态生成配置表单）。"""
    return [cls.metadata() for _, cls in sorted(_REGISTRY.items())]


def discover_builtin_models() -> int:
    """导入 simcore.models 包内全部模块，触发 @register_model。返回注册总数。"""
    import simcore.models as models_pkg

    for info in pkgutil.iter_modules(models_pkg.__path__):
        importlib.import_module(f"simcore.models.{info.name}")
    return len(_REGISTRY)


def load_models_from_dir(path: str | Path) -> int:
    """从外部目录加载用户自定义模型文件（*.py）。返回新增注册数。

    幂等：同一文件重复加载会被跳过（按解析后绝对路径识别），
    避免重复执行触发 model_type 注册冲突。
    """
    directory = Path(path)
    if not directory.is_dir():
        raise RegistryError(f"模型目录不存在: {directory}")
    before = len(_REGISTRY)
    for py_file in sorted(directory.glob("*.py")):
        digest = hashlib.md5(str(py_file.resolve()).encode("utf-8")).hexdigest()[:8]
        module_name = f"scsim_ext_{py_file.stem}_{digest}"
        if module_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec is None or spec.loader is None:
            raise RegistryError(f"无法加载模型文件: {py_file}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    return len(_REGISTRY) - before
