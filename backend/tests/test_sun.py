import math
from datetime import datetime, timezone

from simcore.sun import MEAN_EARTH_R_KM, is_sunlit, sun_unit_eci

J2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def test_sun_unit_is_normalized():
    x, y, z = sun_unit_eci(J2000)
    assert abs(math.sqrt(x * x + y * y + z * z) - 1.0) < 1e-9


def test_sun_unit_direction_at_j2000():
    # J2000 太阳黄经约 280.4°，方向约 (0.18, -0.90, -0.39)
    x, y, z = sun_unit_eci(J2000)
    assert abs(x - 0.180) < 0.02
    assert abs(y - (-0.902)) < 0.02
    assert abs(z - (-0.391)) < 0.02


def test_sunlit_point_on_sunny_side():
    sun_hat = (1.0, 0.0, 0.0)
    assert is_sunlit((7000.0, 0.0, 0.0), sun_hat) is True


def test_point_in_cylindrical_shadow():
    sun_hat = (1.0, 0.0, 0.0)
    # 反太阳侧、垂直距离 < 地球半径 → 处于地影
    assert is_sunlit((-7000.0, 100.0, 0.0), sun_hat) is False


def test_antisun_but_outside_cylinder_is_lit():
    sun_hat = (1.0, 0.0, 0.0)
    assert is_sunlit((-7000.0, 9000.0, 0.0), sun_hat) is True
