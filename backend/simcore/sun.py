"""低精度太阳位置（天文年历，~0.01°）与圆柱影锥受照判定。

复用 SimClock.utc；坐标系 ECI 单位矢量，精度满足态势/裁决用途，
与现有简化 GMST 同档。
"""

from __future__ import annotations

import math
from datetime import datetime

MEAN_EARTH_R_KM = 6371.0


def sun_unit_eci(utc: datetime) -> tuple[float, float, float]:
    """太阳方向单位矢量（ECI）。"""
    jd = 2440587.5 + utc.timestamp() / 86400.0
    n = jd - 2451545.0
    lam_mean = (280.460 + 0.9856474 * n) % 360.0
    g = math.radians((357.528 + 0.9856003 * n) % 360.0)
    lam = math.radians(lam_mean + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g))
    eps = math.radians(23.439 - 4.0e-7 * n)
    x = math.cos(lam)
    y = math.cos(eps) * math.sin(lam)
    z = math.sin(eps) * math.sin(lam)
    norm = math.sqrt(x * x + y * y + z * z)
    return (x / norm, y / norm, z / norm)


def is_sunlit(
    r_km: tuple[float, float, float],
    sun_hat: tuple[float, float, float],
    r_e_km: float = MEAN_EARTH_R_KM,
) -> bool:
    """圆柱影锥近似：反太阳侧且到日地线垂距 < 地球半径 → 处于地影（未受照）。"""
    proj = r_km[0] * sun_hat[0] + r_km[1] * sun_hat[1] + r_km[2] * sun_hat[2]
    if proj >= 0:
        return True  # 朝阳半空间，受照
    perp_x = r_km[0] - proj * sun_hat[0]
    perp_y = r_km[1] - proj * sun_hat[1]
    perp_z = r_km[2] - proj * sun_hat[2]
    perp = math.sqrt(perp_x * perp_x + perp_y * perp_y + perp_z * perp_z)
    return perp >= r_e_km
