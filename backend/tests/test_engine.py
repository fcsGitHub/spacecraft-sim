"""仿真引擎集成测试。"""

import pytest

from simcore import (
    ScheduledCommand,
    SimulationEngine,
    command_from_template,
    scenario_from_dict,
)
from tests.conftest import make_scenario_dict


def build_engine(**overrides) -> SimulationEngine:
    engine = SimulationEngine(scenario_from_dict(make_scenario_dict(**overrides)))
    engine.init()
    return engine


class TestLifecycle:
    def test_init_produces_initial_frame(self):
        engine = build_engine()
        assert engine.last_frame is not None
        assert engine.last_frame.t == 0.0
        state = engine.last_frame.entities["SAT-01"]
        assert state["alt_km"] == pytest.approx(6878 - 6371, abs=15)
        assert len(state["pos_km"]) == 3
        assert state["fuel_pct"] == pytest.approx(80, abs=0.1)
        assert state["payload_state"] == "待机"

    def test_step_advances_clock_and_position(self):
        engine = build_engine()
        p0 = engine.last_frame.entities["SAT-01"]["pos_km"]
        frame = engine.step()
        assert frame.t == 1.0
        p1 = frame.entities["SAT-01"]["pos_km"]
        moved = sum((a - b) ** 2 for a, b in zip(p0, p1)) ** 0.5
        assert 6.0 < moved < 9.0  # LEO 速度 ~7.6 km/s

    def test_finished_after_duration(self):
        engine = build_engine(sim={"epoch": "2026-06-12T04:00:00Z", "duration": 5,
                                   "step": 1, "seed": 1, "record": True})
        while not engine.finished:
            engine.step()
        assert engine.clock.t == pytest.approx(5.0)
        engine.end()
        assert engine.ended

    def test_double_init_rejected(self):
        engine = build_engine()
        with pytest.raises(Exception):
            engine.init()


class TestDeterminism:
    def test_same_seed_same_frames(self):
        e1, e2 = build_engine(), build_engine()
        for _ in range(50):
            f1, f2 = e1.step(), e2.step()
        assert f1.entities == f2.entities


class TestCommands:
    def test_maneuver_raises_semimajor_axis(self):
        engine = build_engine()
        engine.step()
        a0 = engine.last_frame.entities["SAT-01"]["orbit"]["a"]
        cmd = command_from_template("轨道机动", "SAT-01", {"dv": 2.0, "dir": "切向"}, t=1.0)
        engine.inject_now(cmd)
        for _ in range(30):
            frame = engine.step()
        a1 = frame.entities["SAT-01"]["orbit"]["a"]
        assert a1 - a0 > 3.0  # 2 m/s 切向 ≈ +7 km 半长轴

    def test_maneuver_consumes_fuel(self):
        engine = build_engine()
        engine.step()
        f0 = engine.last_frame.entities["SAT-01"]["fuel_pct"]
        engine.inject_now(command_from_template("轨道机动", "SAT-01", {"dv": 2.0, "dir": "切向"}, t=1.0))
        for _ in range(30):
            engine.step()
        f1 = engine.last_frame.entities["SAT-01"]["fuel_pct"]
        assert f0 - f1 == pytest.approx(2.0 * 0.45, abs=0.05)

    def test_payload_command_changes_state(self):
        engine = build_engine()
        engine.inject_now(command_from_template("载荷控制", "SAT-01", {"act": "开机"}, t=0.0))
        frame = engine.step()
        assert frame.entities["SAT-01"]["payload_state"] == "开机"
        assert frame.entities["SAT-01"]["power_w"] == 320

    def test_attitude_command_creates_transient(self):
        engine = build_engine()
        for _ in range(5):
            engine.step()
        dev_before = abs(engine.last_frame.entities["SAT-01"]["att_dev_deg"])
        engine.inject_now(command_from_template("姿态调整", "SAT-01", {"att": "对日定向"}, t=5.0))
        frame = engine.step()
        assert frame.entities["SAT-01"]["att_mode"] == "对日定向"
        assert abs(frame.entities["SAT-01"]["att_dev_deg"]) > dev_before

    def test_scheduled_command_fires_at_time(self):
        engine = build_engine()
        engine.schedule_command(command_from_template("载荷控制", "SAT-02", {"act": "开机"}, t=3.0))
        engine.step()  # t=1
        engine.step()  # t=2
        assert engine.last_frame.entities["SAT-02"]["payload_state"] == "待机"
        engine.step()  # t=3
        frame = engine.step()  # 指令在 t>=3 的步首触发
        assert frame.entities["SAT-02"]["payload_state"] == "开机"

    def test_command_event_recorded_in_frame(self):
        engine = build_engine()
        engine.schedule_command(command_from_template("载荷控制", "SAT-01", {"act": "开机"}, t=0.0))
        frame = engine.step()
        assert any(e.event == "载荷" for e in frame.events)

    def test_inject_unknown_entity_rejected(self):
        engine = build_engine()
        with pytest.raises(Exception):
            engine.inject_now(ScheduledCommand(t=0, entity_id="NOPE", channel="ctr", name="x"))

    def test_dir_fault_disables_thruster(self):
        engine = build_engine()
        engine.inject_now(ScheduledCommand(
            t=0, entity_id="SAT-01", channel="dir", name="fault",
            target_model="thruster", label="推进失效",
        ))
        record = engine.inject_now(
            command_from_template("轨道机动", "SAT-01", {"dv": 2.0, "dir": "切向"}, t=0.0)
        )
        assert record.event == "指令拒绝"


class TestProximityAlert:
    def test_alert_fires_once_for_close_pair(self):
        data = make_scenario_dict()
        # 两星几乎同位置
        data["satellites"][1]["orbit"]["M0"] = 0.5
        engine = SimulationEngine(scenario_from_dict(data))
        engine.alert_threshold_km = 100.0
        engine.init()
        alerts = [e for e in (engine.last_frame.events or ()) if e.event == "预警"]
        for _ in range(5):
            frame = engine.step()
            alerts.extend(e for e in frame.events if e.event == "预警")
        assert len(alerts) == 1  # 去重，仅首次
        assert "SAT-01" in alerts[0].message


class TestRestore:
    def test_mr_snapshot_restore_roundtrip(self):
        engine = build_engine()
        for _ in range(20):
            engine.step()
        snapshot = engine.snapshot_mr()
        pos_at_20 = engine.last_frame.entities["SAT-01"]["pos_km"]
        for _ in range(10):
            engine.step()
        engine.restore_mr(snapshot)
        assert engine.clock.t == pytest.approx(20.0)
        frame = engine.step(0.0)
        assert frame.entities["SAT-01"]["pos_km"] == pytest.approx(pos_at_20, abs=1e-6)


class TestOrbitElementsCache:
    """osculating 根数为降频缓存：无机动时按间隔刷新，点火期间逐步刷新。"""

    def test_periodic_refresh_without_thrust(self):
        engine = build_engine()
        m0_first = engine.last_frame.entities["SAT-01"]["orbit"]["M0"]
        frame = None
        for _ in range(15):  # 超过 ELEMENTS_REFRESH_S=10s（step=1s）
            frame = engine.step()
        m0_later = frame.entities["SAT-01"]["orbit"]["M0"]
        assert m0_later != m0_first  # 平近点角应随刷新前移

    def test_cache_shared_between_refreshes(self):
        engine = build_engine()
        f1 = engine.step()
        f2 = engine.step()
        # 两次刷新之间 orbit 字典对象复用（节省每步换算），且内容一致
        assert f1.entities["SAT-01"]["orbit"] == f2.entities["SAT-01"]["orbit"]

    def test_dir_set_orbit_refreshes_immediately(self):
        engine = build_engine()
        engine.step()
        a0 = engine.last_frame.entities["SAT-01"]["orbit"]["a"]
        engine.inject_now(ScheduledCommand(
            t=1, entity_id="SAT-01", channel="dir", name="set_orbit",
            target_model="orbit", params={"a_km": 7200.0}, label="导调轨道重置",
        ))
        frame = engine.step()
        a1 = frame.entities["SAT-01"]["orbit"]["a"]
        assert a1 == pytest.approx(7200.0, abs=5.0)
        assert a1 - a0 > 100.0


class TestReentryAlertHysteresis:
    """再入告警迟滞：跌破 120km 只告警一次，避免逐步事件洪泛。"""

    def test_reentry_warns_once(self):
        engine = build_engine()
        engine.inject_now(ScheduledCommand(
            t=0, entity_id="SAT-01", channel="dir", name="set_orbit",
            target_model="orbit", params={"a_km": 6450.0}, label="导调降轨",
        ))
        warnings = []
        for _ in range(20):
            frame = engine.step()
            warnings.extend(e for e in frame.events if "再入" in e.message)
        assert len(warnings) == 1
        assert warnings[0].level == "critical"
