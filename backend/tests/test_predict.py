"""预推演（沙箱前向推演）测试。

核心契约：预测与本次推演动力学一致、确定性、且不污染实时引擎。
"""

import pytest

from simcore import (
    SimulationEngine,
    command_from_template,
    predict_tracks,
    scenario_from_dict,
)
from tests.conftest import make_scenario_dict


def build_engine(**overrides) -> SimulationEngine:
    engine = SimulationEngine(scenario_from_dict(make_scenario_dict(**overrides)))
    engine.init()
    return engine


class TestPredictTracks:
    def test_returns_tracks_for_all_entities(self):
        engine = build_engine()
        result = predict_tracks(engine, horizon_s=300, sample_step_s=30)
        assert set(result.tracks) == {"SAT-01", "SAT-02"}
        n = len(result.tracks["SAT-01"])
        assert n == len(result.times)
        assert n >= 10
        first = result.tracks["SAT-01"][0]
        assert len(first["pos_km"]) == 3 and len(first["vel_kmps"]) == 3

    def test_starts_at_current_state(self):
        engine = build_engine()
        for _ in range(20):
            engine.step()
        cur = engine.last_frame.entities["SAT-01"]["pos_km"]
        result = predict_tracks(engine, horizon_s=120, sample_step_s=30)
        assert result.t0 == pytest.approx(engine.clock.t)
        assert result.tracks["SAT-01"][0]["pos_km"] == pytest.approx(cur, abs=1e-6)

    def test_deterministic(self):
        engine = build_engine()
        for _ in range(10):
            engine.step()
        r1 = predict_tracks(engine, 300, 30)
        r2 = predict_tracks(engine, 300, 30)
        assert r1.tracks == r2.tracks
        assert r1.times == r2.times

    def test_does_not_mutate_engine(self):
        engine = build_engine()
        for _ in range(10):
            engine.step()
        t_before = engine.clock.t
        frame_before = engine.last_frame
        pos_before = list(engine.last_frame.entities["SAT-01"]["pos_km"])
        predict_tracks(engine, 3600, 60)
        assert engine.clock.t == t_before
        assert engine.last_frame is frame_before
        assert engine.last_frame.entities["SAT-01"]["pos_km"] == pos_before

    def test_continuation_matches_real_run(self):
        """预测以引擎步长推进时，应与引擎真实继续推进逐点一致（动力学一致性）。"""
        engine = build_engine()
        for _ in range(10):
            engine.step()
        horizon = 10 * engine.step_s
        result = predict_tracks(engine, horizon, sample_step_s=engine.step_s)
        last_pred = result.tracks["SAT-01"][-1]["pos_km"]
        for _ in range(10):
            engine.step()
        real = engine.last_frame.entities["SAT-01"]["pos_km"]
        assert last_pred == pytest.approx(real, abs=1e-6)

    def test_scheduled_maneuver_affects_prediction(self):
        """未触发的预约机动应被沙箱携带，使机动后航迹相对无机动场景发散。"""
        plain = build_engine()
        maneuvered = build_engine()
        maneuvered.schedule_command(
            command_from_template("轨道机动", "SAT-01", {"dv": 5.0, "dir": "切向"}, t=30.0)
        )
        ra = predict_tracks(plain, 600, 30)
        rb = predict_tracks(maneuvered, 600, 30)
        pa = ra.tracks["SAT-01"][-1]["pos_km"]
        pb = rb.tracks["SAT-01"][-1]["pos_km"]
        dist = sum((x - y) ** 2 for x, y in zip(pa, pb)) ** 0.5
        assert dist > 1.0  # km，机动后明显分离

    def test_short_horizon_uses_engine_step(self):
        engine = build_engine()
        result = predict_tracks(engine, 100)
        assert result.step_used_s == pytest.approx(engine.step_s)

    def test_long_horizon_coarsens_step(self):
        """1 天时长触发步长自适应放大，步数受上限约束。"""
        engine = build_engine()
        result = predict_tracks(engine, 86400)
        assert result.step_used_s > engine.step_s
        assert len(result.times) >= 2
        assert len(result.tracks["SAT-01"][-1]["pos_km"]) == 3

    def test_non_positive_horizon_rejected(self):
        engine = build_engine()
        with pytest.raises(ValueError):
            predict_tracks(engine, 0)
        with pytest.raises(ValueError):
            predict_tracks(engine, -10)
