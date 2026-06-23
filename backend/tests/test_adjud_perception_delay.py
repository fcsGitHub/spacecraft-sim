# backend/tests/test_adjud_perception_delay.py
from simcore.model import SimContext
from simcore.params import ParamAttribute, ParamMROutput, ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="", component="adjud:adjud.perception_delay")


def _adj(delay_s=3.0):
    cls = get_model_class("adjud.perception_delay")
    m = cls()
    m.sim_init(_ctx(), (0,)*6, (0,)*6, ParamAttribute(data={"delay_s": delay_s}))
    return m


def _env(t, bx):
    return {"sim_time": t, "entities": {
        "R1": {"faction": "红方", "pos_km": [0, 0, 0], "vel_kmps": [0, 0, 0]},
        "B1": {"faction": "蓝方", "pos_km": [bx, 0, 0], "vel_kmps": [1, 0, 0]},
    }}


def test_reports_delayed_position():
    m = _adj(delay_s=3.0)
    # 喂入 t=1..5，B1 的 x = t（每步前进 1）
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env(t, bx=t)))
    perc = res.rt_output.data["perception"]
    # t=5 看到 t-3=2 的位置
    assert perc["红方"]["B1"]["pos_km"] == [2.0, 0, 0]
    assert perc["红方"]["B1"]["source"] == "delayed"
    assert perc["红方"]["B1"]["age_s"] == 3.0


def test_early_steps_use_oldest_available():
    m = _adj(delay_s=10.0)
    res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env(1.0, bx=1.0)))
    # 仅一帧历史，滞后不足 10s → 取最早可用（age=0）
    assert res.rt_output.data["perception"]["红方"]["B1"]["pos_km"] == [1.0, 0, 0]
    assert res.rt_output.data["perception"]["红方"]["B1"]["age_s"] == 0.0


def test_restore_round_trip():
    m = _adj(delay_s=3.0)
    for t in (1.0, 2.0, 3.0, 4.0, 5.0):
        res = m.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env(t, bx=t)))
    mr = res.mr_output
    m2 = _adj(delay_s=3.0)
    m2.sim_restore(ParamMROutput(time=mr.time, state=dict(mr.state)))
    res2 = m2.sim_advance(_ctx(), (0,)*6, (0,)*6, 1.0, ParamRTInput(env=_env(6.0, bx=6.0)))
    # 恢复后 t=6 看到 t-3=3 的位置
    assert res2.rt_output.data["perception"]["红方"]["B1"]["pos_km"] == [3.0, 0, 0]
