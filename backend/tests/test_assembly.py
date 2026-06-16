"""组件链组装与外部模型扩展测试（含 examples/models 大气阻力示例）。"""

import math
from pathlib import Path

import pytest

from simcore import ScenarioError, SimulationEngine, scenario_from_dict, validate_scenario
from simcore.orbits import MU_EARTH
from simcore.registry import list_models, load_models_from_dir
from tests.conftest import make_scenario_dict

EXAMPLES_MODELS_DIR = Path(__file__).resolve().parents[1] / "examples" / "models"


def ensure_drag_model_loaded() -> None:
    if not any(m["model_type"] == "perturb.drag_atmo" for m in list_models()):
        load_models_from_dir(EXAMPLES_MODELS_DIR)


def custom_chain_scenario(with_drag: bool):
    """单星低轨场景，纯二体（关闭 J2），便于用比机械能验证阻力效果。"""
    comps = [
        {"name": "thruster", "model": "prop.thruster"},
        {"name": "orbit", "model": "orbit.j2", "params": {"enable_j2": False}},
    ]
    if with_drag:
        comps.insert(1, {
            "name": "drag", "model": "perturb.drag_atmo",
            "params": {"cd": 2.2, "area_m2": 12.0},
        })
    data = make_scenario_dict(
        sim={"epoch": "2026-06-12T04:00:00Z", "duration": 7200,
             "step": 10, "seed": 1, "record": False},
    )
    data["satellites"] = [data["satellites"][0]]
    data["satellites"][0]["orbit"]["a"] = 6700  # 高度约 330 km，阻力可测
    data["satellites"][0]["components"] = comps
    return data


def specific_energy(state) -> float:
    p, v = state["pos_km"], state["vel_kmps"]
    r_m = math.sqrt(p[0] ** 2 + p[1] ** 2 + p[2] ** 2) * 1000.0
    v2 = (v[0] ** 2 + v[1] ** 2 + v[2] ** 2) * 1e6
    return v2 / 2 - MU_EARTH / r_m


class TestCustomComponents:
    def test_default_chain_when_components_absent(self):
        engine = SimulationEngine(scenario_from_dict(make_scenario_dict()))
        infos = engine.entity_infos()
        names = [c["name"] for c in infos[0]["components"]]
        assert names == ["thruster", "orbit", "attitude", "payload"]

    def test_custom_chain_builds_and_runs(self):
        ensure_drag_model_loaded()
        engine = SimulationEngine(scenario_from_dict(custom_chain_scenario(with_drag=True)))
        engine.init()
        names = [c["name"] for c in engine.entity_infos()[0]["components"]]
        assert names == ["thruster", "drag", "orbit"]
        frame = engine.step()
        state = frame.entities["SAT-01"]
        assert "pos_km" in state and "drag_accel_mps2" in state
        assert "payload_state" not in state  # 自定义链未挂载载荷

    def test_unknown_model_raises_scenario_error(self):
        data = make_scenario_dict()
        data["satellites"][0]["components"] = [{"name": "x", "model": "no.such_model"}]
        with pytest.raises(ScenarioError, match="no.such_model"):
            SimulationEngine(scenario_from_dict(data))

    def test_components_validation(self):
        data = make_scenario_dict()
        data["satellites"][0]["components"] = "orbit"  # 非数组
        errors, _ = validate_scenario(data)
        assert any("components" in e["msg"] for e in errors)

        data["satellites"][0]["components"] = [
            {"name": "orbit", "model": "orbit.j2"},
            {"name": "orbit", "model": "orbit.j2"},  # 重名
        ]
        errors, _ = validate_scenario(data)
        assert any("组件名重复" in e["msg"] for e in errors)

        data["satellites"][0]["components"] = [{"name": "orbit"}]  # 缺 model
        errors, _ = validate_scenario(data)
        assert any("model" in e["msg"] for e in errors)

    def test_satellite_attrs_injected_into_custom_chain(self):
        """标准模型在自定义链中仍自动注入卫星派生属性（燃料/轨道根数）。"""
        ensure_drag_model_loaded()
        engine = SimulationEngine(scenario_from_dict(custom_chain_scenario(with_drag=False)))
        engine.init()
        state = engine.last_frame.entities["SAT-01"]
        assert state["fuel_pct"] == pytest.approx(80, abs=0.1)
        assert state["orbit"]["a"] == pytest.approx(6700, abs=5)


class TestDragExampleModel:
    def test_drag_dissipates_orbital_energy(self):
        """同初始条件下，带阻力的轨道比机械能应明显低于纯二体。"""
        ensure_drag_model_loaded()
        eng_ref = SimulationEngine(scenario_from_dict(custom_chain_scenario(with_drag=False)))
        eng_drag = SimulationEngine(scenario_from_dict(custom_chain_scenario(with_drag=True)))
        eng_ref.init()
        eng_drag.init()
        e0 = specific_energy(eng_ref.last_frame.entities["SAT-01"])
        for _ in range(360):  # 1 小时（步长 10 s）
            f_ref = eng_ref.step()
            f_drag = eng_drag.step()
        e_ref = specific_energy(f_ref.entities["SAT-01"])
        e_drag = specific_energy(f_drag.entities["SAT-01"])
        assert abs(e_ref - e0) < 5.0          # 纯二体 RK4 能量近守恒
        assert e_ref - e_drag > 100.0          # 阻力耗散明显（预期 ~280 J/kg）

    def test_drag_opposes_velocity(self):
        """阻力加速度方向与速度相反：合加速度·速度 < 0（无推力时）。"""
        ensure_drag_model_loaded()
        engine = SimulationEngine(scenario_from_dict(custom_chain_scenario(with_drag=True)))
        engine.init()
        frame = engine.step()
        state = frame.entities["SAT-01"]
        acc = state["thrust_accel_mps2"]
        vel = state["vel_kmps"]
        dot = acc[0] * vel[0] + acc[1] * vel[1] + acc[2] * vel[2]
        assert state["drag_accel_mps2"] > 0
        assert dot < 0

    def test_idempotent_dir_load(self):
        ensure_drag_model_loaded()
        added = load_models_from_dir(EXAMPLES_MODELS_DIR)  # 重复加载不应冲突
        assert added == 0
