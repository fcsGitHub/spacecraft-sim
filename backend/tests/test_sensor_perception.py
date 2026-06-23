# backend/tests/test_sensor_perception.py
from simcore.bus import BusMessage
from simcore.model import SimContext
from simcore.params import ParamAttribute, ParamCtrInput, ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx(eid="R1"):
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id=eid, component="payload")


def _sensor(**attr):
    cls = get_model_class("sensor.perception")
    m = cls()
    m.sim_init(_ctx(), (0,) * 6, (0,) * 6, ParamAttribute(data=attr))
    return m


def _rt(messages=(), faction="红方"):
    return ParamRTInput(env={}, upstream={"id": "R1", "faction": faction}, messages=messages)


def test_publishes_scan_when_on():
    res = _sensor(max_range_km=2500, state="开机").sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, _rt())
    scan = next(m for m in res.messages if m.topic == "perception.scan")
    assert scan.data["observer"] == "R1"
    assert scan.data["faction"] == "红方"
    assert scan.data["max_range_km"] == 2500


def test_no_scan_when_off():
    res = _sensor(state="关闭").sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, _rt())
    assert all(m.topic != "perception.scan" for m in res.messages)


def test_ctrl_toggles_state():
    m = _sensor(state="关闭")
    assert m.sim_ctr_response(ParamCtrInput(name="sensor_ctrl", params={"act": "开机"})) == 0
    res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, _rt())
    assert any(m2.topic == "perception.scan" for m2 in res.messages)


def test_consumes_result_for_own_observer():
    m = _sensor(state="开机")
    result = BusMessage(topic="perception.result",
                        data={"observer": "R1", "sensed": [{"id": "B1"}, {"id": "B2"}]})
    res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, _rt(messages=(result,)))
    assert res.rt_output.data["sensed_count"] == 2
    assert set(res.rt_output.data["sensed_ids"]) == {"B1", "B2"}


def test_ignores_result_for_other_observer():
    m = _sensor(state="开机")
    result = BusMessage(topic="perception.result",
                        data={"observer": "R9", "sensed": [{"id": "B1"}]})
    res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, _rt(messages=(result,)))
    assert res.rt_output.data["sensed_count"] == 0
