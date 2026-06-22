from simcore.bus import BusMessage
from simcore.model import SimContext
from simcore.params import ParamAttribute, ParamCtrInput, ParamRTInput
from simcore.registry import discover_builtin_models, get_model_class

discover_builtin_models()


def _ctx(entity="SAT-01"):
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id=entity, component="camera")


def _camera():
    cls = get_model_class("sensor.camera")
    cam = cls()
    cam.sim_init(_ctx(), (0,) * 6, (0,) * 6,
                 ParamAttribute(data={"fov_deg": 5, "max_range_km": 2000,
                                      "ifov_urad": 50, "gsd_threshold_m": 5}))
    return cam


def test_take_photo_publishes_request_message():
    cam = _camera()
    cam.sim_ctr_response(ParamCtrInput(entity_id="SAT-01", name="take_photo",
                                       params={"target": "SAT-02"}))
    res = cam.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput())
    topics = [m.topic for m in res.messages]
    assert "camera.photo_request" in topics
    req = next(m for m in res.messages if m.topic == "camera.photo_request")
    assert req.data["photographer"] == "SAT-01"
    assert req.data["target"] == "SAT-02"
    assert req.data["request_id"] == 1
    assert req.data["max_range_km"] == 2000


def test_no_request_when_idle():
    cam = _camera()
    res = cam.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput())
    assert all(m.topic != "camera.photo_request" for m in res.messages)


def test_consumes_photo_result_and_counts_success():
    cam = _camera()
    result = BusMessage(topic="camera.photo_result",
                        data={"request_id": 1, "success": True, "quality": 0.8})
    res = cam.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                          ParamRTInput(messages=(result,)))
    assert res.rt_output.data["shots"] == 1
    assert res.rt_output.data["last_result"] == "成功"


def test_request_id_is_deterministic_increment():
    cam = _camera()
    for expected in (1, 2):
        cam.sim_ctr_response(ParamCtrInput(entity_id="SAT-01", name="take_photo",
                                           params={"target": "SAT-02"}))
        res = cam.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0, ParamRTInput())
        req = next(m for m in res.messages if m.topic == "camera.photo_request")
        assert req.data["request_id"] == expected
