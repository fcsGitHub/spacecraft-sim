from simcore.model import SimContext
from simcore.params import ParamAttribute, ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _adj(threshold=100.0):
    cls = get_model_class("adjud.proximity")
    m = cls()
    m.sim_init(SimContext(engine=None, entity_id="", component="adjud:adjud.proximity"),
               (0,) * 6, (0,) * 6, ParamAttribute(data={"threshold_km": threshold}))
    return m


def _env(states):
    return {"sim_time": 0.0, "entities": states, "sun_eci": (1.0, 0.0, 0.0)}


def test_alert_when_within_threshold():
    states = {"A": {"pos_km": [7000, 0, 0]}, "B": {"pos_km": [7050, 0, 0]}}
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput(env=_env(states)))
    assert any(e.event == "预警" for e in res.key_outputs)


def test_no_alert_when_far():
    states = {"A": {"pos_km": [7000, 0, 0]}, "B": {"pos_km": [8000, 0, 0]}}
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput(env=_env(states)))
    assert all(e.event != "预警" for e in res.key_outputs)


def test_hysteresis_no_duplicate_alert():
    m = _adj()
    states = {"A": {"pos_km": [7000, 0, 0]}, "B": {"pos_km": [7050, 0, 0]}}
    first = m.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput(env=_env(states)))
    second = m.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput(env=_env(states)))
    assert sum(e.event == "预警" for e in first.key_outputs) == 1
    assert sum(e.event == "预警" for e in second.key_outputs) == 0


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="", component="adjud:adjud.proximity")
