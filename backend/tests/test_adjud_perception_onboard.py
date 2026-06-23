# backend/tests/test_adjud_perception_onboard.py
from simcore.bus import BusMessage
from simcore.model import SimContext
from simcore.params import ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="", component="adjud:adjud.perception_onboard")


def _adj():
    return get_model_class("adjud.perception_onboard")()


def _scan(observer="R1", faction="红方", rng=1000.0, tf=""):
    return BusMessage(topic="perception.scan", data={
        "observer": observer, "faction": faction, "max_range_km": rng, "target_factions": tf})


def _env():
    return {"sim_time": 2.0, "entities": {
        "R1": {"faction": "红方", "pos_km": [0, 0, 0], "vel_kmps": [0, 0, 0]},
        "B1": {"faction": "蓝方", "pos_km": [500, 0, 0], "vel_kmps": [0, 1, 0]},   # 距 R1 500
        "B2": {"faction": "蓝方", "pos_km": [5000, 0, 0], "vel_kmps": [0, 1, 0]},  # 距 R1 5000
    }}


def test_senses_within_range_only():
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0,
                             ParamRTInput(env=_env(), messages=(_scan(rng=1000.0),)))
    perc = res.rt_output.data["perception"]
    assert "B1" in perc["红方"]            # 500 ≤ 1000
    assert "B2" not in perc["红方"]        # 5000 > 1000
    assert perc["红方"]["B1"]["source"] == "onboard"
    assert perc["红方"]["B1"]["observers"] == ["R1"]


def test_publishes_result_to_observer():
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0,
                             ParamRTInput(env=_env(), messages=(_scan(rng=1000.0),)))
    result = next(m for m in res.messages if m.topic == "perception.result")
    assert result.data["observer"] == "R1"
    assert [s["id"] for s in result.data["sensed"]] == ["B1"]


def test_target_factions_filter():
    env = _env()
    env["entities"]["N1"] = {"faction": "中立", "pos_km": [100, 0, 0], "vel_kmps": [0, 0, 0]}
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0,
                             ParamRTInput(env=env, messages=(_scan(rng=1000.0, tf="蓝方"),)))
    perc = res.rt_output.data["perception"]
    assert "B1" in perc["红方"]
    assert "N1" not in perc["红方"]        # 限定只感知蓝方


def test_no_self_sensing():
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0,
                             ParamRTInput(env=_env(), messages=(_scan(rng=100000.0),)))
    assert "R1" not in res.rt_output.data["perception"].get("红方", {})
