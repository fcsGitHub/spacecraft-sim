"""硬验收：同场景+种子+指令序列 → 逐帧逐位复现。"""
from simcore.engine import ScheduledCommand, SimulationEngine
from simcore.registry import discover_builtin_models
from simcore.scenario import scenario_from_dict

discover_builtin_models()


def _scn():
    return scenario_from_dict({
        "meta": {"name": "determinism"},
        "sim": {"epoch": "2026-03-01T00:00:00Z", "duration": 1200, "step": 10, "seed": 42},
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
                  "params": {"max_range_km": 6000, "gsd_threshold_m": 300}}]},
            {"id": "SAT-02", "name": "tgt", "faction": "蓝方", "mass": 400, "fuel": 60,
             "payload": {"type": "通信", "state": "待机", "power": 200},
             "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 0.6}}],
        "adjudications": [{"type": "adjud.photo"},
                          {"type": "adjud.proximity", "params": {"threshold_km": 150}}],
    })


def _run():
    eng = SimulationEngine(_scn()); eng.init()
    eng.schedule_command(ScheduledCommand(
        t=30, entity_id="SAT-01", channel="ctr", name="take_photo",
        target_model="camera", params={"target": "SAT-02"}))
    return [eng.step().to_dict() for _ in range(40)]


def test_two_runs_are_bit_identical():
    assert _run() == _run()
