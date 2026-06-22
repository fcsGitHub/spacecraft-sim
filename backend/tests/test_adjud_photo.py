from simcore.bus import BusMessage
from simcore.model import SimContext
from simcore.params import ParamAttribute, ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="", component="adjud:adjud.photo")


def _adj():
    cls = get_model_class("adjud.photo")
    m = cls()
    m.sim_init(_ctx(), (0,) * 6, (0,) * 6, ParamAttribute())
    return m


def _request(target="SAT-02", **over):
    data = {"photographer": "SAT-01", "target": target, "request_id": 1,
            "fov_deg": 5.0, "max_range_km": 2000.0, "sun_exclusion_deg": 30.0,
            "ifov_urad": 50.0, "gsd_threshold_m": 100.0, "point_mode": "跟踪目标"}
    data.update(over)
    return BusMessage(topic="camera.photo_request", data=data)


def _env(cam, tgt, sun=(0.0, 0.0, 1.0)):
    return {"sim_time": 0.0, "sun_eci": sun,
            "entities": {"SAT-01": {"pos_km": list(cam)}, "SAT-02": {"pos_km": list(tgt)}}}


def _result(res):
    return next(m for m in res.messages if m.topic == "camera.photo_result").data


def test_success_close_range_sunlit():
    # 相机与目标相距 100 km，太阳沿 +x，目标在 +x 侧受照
    env = _env((7000, 0, 0), (7000, 100, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(),)))
    out = _result(res)
    assert out["success"] is True
    assert 0.0 < out["quality"] <= 1.0


def test_fail_out_of_range():
    env = _env((7000, 0, 0), (7000, 5000, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(),)))
    out = _result(res)
    assert out["success"] is False
    assert out["reason"] == "超出作用距离"


def test_fail_earth_occlusion():
    # 相机与目标分居地球两侧，视线穿过地球
    env = _env((7000, 0, 0), (-7000, 0, 0), sun=(0.0, 0.0, 1.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(max_range_km=20000.0),)))
    out = _result(res)
    assert out["success"] is False
    assert out["reason"] == "地球遮挡"


def test_fail_target_in_shadow():
    # 目标处于反太阳侧圆柱影锥内（太阳 +x，目标在 -x、垂距 < R_E）
    env = _env((-6900, 0, 0), (-7000, 100, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(),)))
    out = _result(res)
    assert out["success"] is False
    assert out["reason"] == "目标未受照"


def test_fail_sun_glare():
    # 视线方向与太阳方向几乎一致 → 眩光（目标在相机正后方对着太阳）
    env = _env((7000, 0, 0), (7100, 0, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(),)))
    out = _result(res)
    assert out["success"] is False
    assert out["reason"] == "太阳眩光"


def test_fail_resolution_insufficient():
    # 远距 + 大 ifov → GSD 超门限（门限设小）
    env = _env((7000, 0, 0), (7000, 1500, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(gsd_threshold_m=1.0),)))
    out = _result(res)
    assert out["success"] is False
    assert out["reason"] == "分辨率不足"


def test_emits_key_output_event():
    env = _env((7000, 0, 0), (7000, 100, 0), sun=(1.0, 0.0, 0.0))
    res = _adj().sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                             ParamRTInput(env=env, messages=(_request(),)))
    assert any(e.event == "裁决" for e in res.key_outputs)
