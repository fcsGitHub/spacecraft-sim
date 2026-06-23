# backend/tests/test_adjud_perception_full.py
from simcore.model import SimContext
from simcore.params import ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="", component="adjud:adjud.perception_full")


def _adj():
    return get_model_class("adjud.perception_full")()


def _env():
    return {"sim_time": 5.0, "entities": {
        "R1": {"faction": "红方", "pos_km": [1, 0, 0], "vel_kmps": [0, 1, 0]},
        "B1": {"faction": "蓝方", "pos_km": [2, 0, 0], "vel_kmps": [0, 2, 0]},
    }}


def test_each_faction_sees_opponent_realtime():
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env()))
    perc = res.rt_output.data["perception"]
    assert perc["红方"]["B1"]["pos_km"] == [2, 0, 0]
    assert perc["红方"]["B1"]["source"] == "realtime"
    assert perc["红方"]["B1"]["age_s"] == 0.0
    assert perc["蓝方"]["R1"]["pos_km"] == [1, 0, 0]
    assert "R1" not in perc["红方"]      # 己方不进感知图


def test_no_bus_messages():
    res = _adj().sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env()))
    assert res.messages == ()
