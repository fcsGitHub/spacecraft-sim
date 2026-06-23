# backend/tests/test_perception_frame.py
from simcore.engine import SimulationEngine
from simcore.scenario import scenario_from_dict
from tests.conftest import make_scenario_dict


def _scn_with(adjuds, sat0_components=None):
    data = make_scenario_dict()
    data["adjudications"] = adjuds
    if sat0_components:
        data["satellites"][0]["components"] = sat0_components
    return scenario_from_dict(data)


def test_full_perception_in_frame():
    eng = SimulationEngine(_scn_with([{"type": "adjud.perception_full"}]))
    eng.init()
    frame = eng.step()
    # 默认 conftest：SAT-01 红方、SAT-02 蓝方
    assert "SAT-02" in frame.perception["红方"]
    assert frame.perception["红方"]["SAT-02"]["source"] == "realtime"
    assert "perception" in frame.to_dict()


def test_onboard_perception_merges_over_delay():
    comps = [
        {"name": "thruster", "model": "prop.thruster"},
        {"name": "orbit", "model": "orbit.j2"},
        {"name": "attitude", "model": "aocs.simple"},
        {"name": "payload", "model": "payload.generic"},
        {"name": "sensor", "model": "sensor.perception", "params": {"max_range_km": 100000, "state": "开机"}},
    ]
    eng = SimulationEngine(_scn_with(
        [{"type": "adjud.perception_delay", "params": {"delay_s": 30}},
         {"type": "adjud.perception_onboard"}],
        sat0_components=comps))
    eng.init()
    frame = None
    for _ in range(3):                       # 跨步让 scan→onboard 命中
        frame = eng.step()
    sensed = frame.perception.get("红方", {}).get("SAT-02")
    assert sensed is not None
    assert sensed["source"] == "onboard"     # 实时命中覆盖延时（age 更小）


def test_no_adjud_perception_empty():
    eng = SimulationEngine(_scn_with([{"type": "adjud.proximity", "params": {"threshold_km": 100}}]))
    eng.init()
    frame = eng.step()
    assert frame.perception == {}
