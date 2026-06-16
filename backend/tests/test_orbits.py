"""轨道力学工具单元测试。"""

import math

import pytest

from simcore import orbits


class TestElementsStateRoundtrip:
    def test_roundtrip_leo(self):
        state = orbits.elements_to_state(6878137.0, 0.001, 97.5, 60.0, 90.0, 45.0)
        elems = orbits.state_to_elements(state)
        assert elems["a_m"] == pytest.approx(6878137.0, rel=1e-9)
        assert elems["e"] == pytest.approx(0.001, abs=1e-9)
        assert elems["i_deg"] == pytest.approx(97.5, abs=1e-9)
        assert elems["raan_deg"] == pytest.approx(60.0, abs=1e-9)
        assert elems["argp_deg"] == pytest.approx(90.0, abs=1e-6)
        assert elems["nu_deg"] == pytest.approx(45.0, abs=1e-6)

    def test_circular_speed(self):
        state = orbits.elements_to_state(7000e3, 0.0, 0.0, 0.0, 0.0, 0.0)
        v = math.sqrt(state[3] ** 2 + state[4] ** 2 + state[5] ** 2)
        assert v == pytest.approx(math.sqrt(orbits.MU_EARTH / 7000e3), rel=1e-9)

    def test_invalid_elements_rejected(self):
        with pytest.raises(ValueError):
            orbits.elements_to_state(-1.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        with pytest.raises(ValueError):
            orbits.elements_to_state(7000e3, 1.5, 0.0, 0.0, 0.0, 0.0)


class TestAnomalyConversion:
    @pytest.mark.parametrize("m_deg", [0.0, 45.0, 120.0, 250.0, 359.0])
    @pytest.mark.parametrize("e", [0.0, 0.001, 0.1, 0.7])
    def test_roundtrip(self, m_deg, e):
        nu = orbits.mean_to_true_deg(m_deg, e)
        back = orbits.true_to_mean_deg(nu, e)
        assert back == pytest.approx(m_deg, abs=1e-8)

    def test_circular_identity(self):
        assert orbits.mean_to_true_deg(73.0, 0.0) == pytest.approx(73.0, abs=1e-9)


class TestPropagation:
    def test_period_returns_to_start(self):
        """无 J2 时推进一个周期应回到初始位置。"""
        a = 7000e3
        state0 = orbits.elements_to_state(a, 0.001, 30.0, 10.0, 20.0, 0.0)
        period = 2 * math.pi * math.sqrt(a**3 / orbits.MU_EARTH)
        state1 = orbits.propagate(state0, period, enable_j2=False, max_substep=10.0)
        for i in range(3):
            assert state1[i] == pytest.approx(state0[i], abs=200.0)  # 200 m 容差

    def test_energy_conservation_no_thrust(self):
        state0 = orbits.elements_to_state(6878e3, 0.01, 51.6, 0.0, 0.0, 0.0)
        state1 = orbits.propagate(state0, 3000.0, enable_j2=False)

        def energy(s):
            r = math.sqrt(s[0] ** 2 + s[1] ** 2 + s[2] ** 2)
            v2 = s[3] ** 2 + s[4] ** 2 + s[5] ** 2
            return v2 / 2 - orbits.MU_EARTH / r

        assert energy(state1) == pytest.approx(energy(state0), rel=1e-9)

    def test_j2_raan_regression_for_prograde(self):
        """顺行轨道 J2 应使升交点西退（RAAN 减小）。"""
        state = orbits.elements_to_state(6878e3, 0.001, 51.6, 100.0, 0.0, 0.0)
        out = orbits.propagate(state, 5400.0, enable_j2=True)
        elems = orbits.state_to_elements(out)
        # 5400s 约一圈，RAAN 应减小但远小于 1 度
        diff = (elems["raan_deg"] - 100.0 + 180) % 360 - 180
        assert -1.0 < diff < 0.0

    def test_tangential_accel_raises_orbit(self):
        state = orbits.elements_to_state(6878e3, 0.001, 0.0, 0.0, 0.0, 0.0)
        v = (state[3], state[4], state[5])
        vmag = math.sqrt(sum(x * x for x in v))
        unit = tuple(x / vmag for x in v)
        accel = tuple(u * 0.5 for u in unit)  # 0.5 m/s² 切向
        out = orbits.propagate(state, 10.0, extra_accel=accel, enable_j2=False)
        assert orbits.state_to_elements(out)["a_m"] > 6878e3


class TestGeodetic:
    def test_equator_point(self):
        geo = orbits.eci_to_geodetic((orbits.RE_EARTH + 500e3, 0.0, 0.0), gmst=0.0)
        assert geo["lat_deg"] == pytest.approx(0.0, abs=1e-9)
        assert geo["lon_deg"] == pytest.approx(0.0, abs=1e-9)
        assert geo["alt_m"] == pytest.approx(500e3, abs=1.0)

    def test_pole(self):
        geo = orbits.eci_to_geodetic((0.0, 0.0, 7000e3), gmst=1.0)
        assert geo["lat_deg"] == pytest.approx(90.0, abs=1e-6)


class TestGmstLinearity:
    """模型用 历元GMST + 自转率×t 线性递推，须与完整公式严格一致。"""

    def test_linear_extrapolation_matches_formula(self):
        from datetime import datetime, timedelta, timezone

        from simcore.timebase import OMEGA_EARTH_RAD_PER_S, gmst_rad

        epoch = datetime(2026, 6, 12, 4, 0, 0, tzinfo=timezone.utc)
        g0 = gmst_rad(epoch)
        for t in (0.0, 60.0, 3600.0, 86400.0, 7 * 86400.0):
            expected = gmst_rad(epoch + timedelta(seconds=t))
            linear = (g0 + OMEGA_EARTH_RAD_PER_S * t) % (2 * math.pi)
            diff = abs(linear - expected)
            diff = min(diff, 2 * math.pi - diff)  # 角度回绕
            assert diff < 1e-9, f"t={t}: linear={linear} formula={expected}"
