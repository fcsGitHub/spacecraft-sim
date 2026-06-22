from simcore.engine import ScheduledCommand, SimulationEngine
from simcore.registry import discover_builtin_models
from simcore.scenario import scenario_from_dict

discover_builtin_models()


def _scn(extra=None):
    base = {
        "meta": {"name": "engine-test"},
        "sim": {"epoch": "2026-01-01T00:00:00Z", "duration": 600, "step": 10, "seed": 7},
        "satellites": [
            {"id": "SAT-01", "name": "obs", "faction": "红方", "mass": 500, "fuel": 80,
             "payload": {"type": "光学成像", "state": "待机", "power": 300},
             "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 0},
             "components": [
                 {"name": "thruster", "model": "prop.thruster"},
                 {"name": "orbit", "model": "orbit.j2"},
                 {"name": "attitude", "model": "aocs.simple"},
                 {"name": "payload", "model": "payload.generic"},
                 {"name": "camera", "model": "sensor.camera",
                  "params": {"max_range_km": 5000, "gsd_threshold_m": 200}},
             ]},
            {"id": "SAT-02", "name": "tgt", "faction": "蓝方", "mass": 400, "fuel": 60,
             "payload": {"type": "通信", "state": "待机", "power": 200},
             "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 0.5}},
        ],
        "adjudications": [
            {"type": "adjud.photo"},
            {"type": "adjud.proximity", "params": {"threshold_km": 100}},
        ],
    }
    if extra:
        base.update(extra)
    return scenario_from_dict(base)


def test_init_builds_composites_and_initial_frame():
    eng = SimulationEngine(_scn())
    eng.init()
    assert eng.last_frame is not None
    assert "SAT-01" in eng.last_frame.entities
    infos = {e["id"]: e for e in eng.entity_infos()}
    names = [c["name"] for c in infos["SAT-01"]["components"]]
    assert names == ["thruster", "orbit", "attitude", "payload", "camera"]


def test_step_is_deterministic():
    a = SimulationEngine(_scn()); a.init()
    b = SimulationEngine(_scn()); b.init()
    for _ in range(10):
        fa, fb = a.step(), b.step()
        assert fa.to_dict() == fb.to_dict()


def test_photo_command_flows_through_bus_to_adjudication():
    eng = SimulationEngine(_scn()); eng.init()
    eng.schedule_command(ScheduledCommand(
        t=10, entity_id="SAT-01", channel="ctr", name="take_photo",
        target_model="camera", params={"target": "SAT-02"}, label="拍照"))
    verdict_seen = False
    for _ in range(5):
        frame = eng.step()
        if any(ev["type"] == "裁决" for ev in frame.to_dict()["events"]):
            verdict_seen = True
    assert verdict_seen  # 相机请求经总线到达裁决并回出裁决事件


def test_proximity_alert_emitted():
    eng = SimulationEngine(_scn()); eng.init()
    saw_alert = False
    for _ in range(20):
        frame = eng.step()
        if any(ev["type"] == "预警" for ev in frame.to_dict()["events"]):
            saw_alert = True
    assert saw_alert  # 同轨近距两星触发接近预警裁决


def test_snapshot_restore_roundtrip():
    eng = SimulationEngine(_scn()); eng.init()
    for _ in range(3):
        eng.step()
    snap = eng.snapshot_mr()
    clone = SimulationEngine(_scn()); clone.init()
    clone.restore_mr(snap)
    f1 = eng.step()
    f2 = clone.step()
    assert f1.to_dict()["entities"] == f2.to_dict()["entities"]


def test_default_adjudication_is_proximity_when_absent():
    eng = SimulationEngine(_scn({"adjudications": []})); eng.init()
    # 缺省回退：仍能产生接近预警
    saw = False
    for _ in range(20):
        if any(ev["type"] == "预警" for ev in eng.step().to_dict()["events"]):
            saw = True
    assert saw


def test_alert_threshold_property_proxies_proximity():
    # server.runtime / predict 仍用 engine.alert_threshold_km；代理到 adjud.proximity
    eng = SimulationEngine(_scn()); eng.init()
    eng.alert_threshold_km = 250.0
    assert eng.alert_threshold_km == 250.0
