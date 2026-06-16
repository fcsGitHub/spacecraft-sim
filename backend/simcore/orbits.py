"""轨道力学工具：开普勒根数与惯性系状态互换、J2 摄动加速度、RK4 积分。

坐标系：ECI（地心惯性系，米 / 米每秒）。角度接口统一用度。
"""

from __future__ import annotations

import math

MU_EARTH = 3.986004418e14   # 地球引力常数 (m^3/s^2)
RE_EARTH = 6378137.0        # 地球赤道半径 (m)
J2_EARTH = 1.08262668e-3    # J2 带谐项系数

Vec3 = tuple[float, float, float]
State = tuple[float, float, float, float, float, float]  # rx ry rz vx vy vz


def elements_to_state(
    a_m: float, e: float, i_deg: float, raan_deg: float, argp_deg: float, nu_deg: float
) -> State:
    """经典轨道根数 -> ECI 位置速度。"""
    if a_m <= 0:
        raise ValueError(f"半长轴必须为正: {a_m}")
    if not 0 <= e < 1:
        raise ValueError(f"仅支持椭圆轨道 0<=e<1: {e}")
    i = math.radians(i_deg)
    raan = math.radians(raan_deg)
    argp = math.radians(argp_deg)
    nu = math.radians(nu_deg)

    p = a_m * (1 - e * e)
    r_mag = p / (1 + e * math.cos(nu))
    # 近焦点坐标系
    r_pf = (r_mag * math.cos(nu), r_mag * math.sin(nu), 0.0)
    coef = math.sqrt(MU_EARTH / p)
    v_pf = (-coef * math.sin(nu), coef * (e + math.cos(nu)), 0.0)

    cr, sr = math.cos(raan), math.sin(raan)
    ci, si = math.cos(i), math.sin(i)
    cw, sw = math.cos(argp), math.sin(argp)
    # 近焦点 -> ECI 旋转矩阵（R3(-raan)R1(-i)R3(-argp)）
    row1 = (cr * cw - sr * sw * ci, -cr * sw - sr * cw * ci, sr * si)
    row2 = (sr * cw + cr * sw * ci, -sr * sw + cr * cw * ci, -cr * si)
    row3 = (sw * si, cw * si, ci)

    def rot(v: Vec3) -> Vec3:
        return (
            row1[0] * v[0] + row1[1] * v[1] + row1[2] * v[2],
            row2[0] * v[0] + row2[1] * v[1] + row2[2] * v[2],
            row3[0] * v[0] + row3[1] * v[1] + row3[2] * v[2],
        )

    r = rot(r_pf)
    v = rot(v_pf)
    return (r[0], r[1], r[2], v[0], v[1], v[2])


def state_to_elements(state: State) -> dict[str, float]:
    """ECI 位置速度 -> 经典轨道根数（角度制）。"""
    rx, ry, rz, vx, vy, vz = state
    r_mag = math.sqrt(rx * rx + ry * ry + rz * rz)
    v_mag = math.sqrt(vx * vx + vy * vy + vz * vz)
    # 角动量
    hx, hy, hz = (ry * vz - rz * vy, rz * vx - rx * vz, rx * vy - ry * vx)
    h_mag = math.sqrt(hx * hx + hy * hy + hz * hz)
    # 节线
    nx, ny = -hy, hx
    n_mag = math.sqrt(nx * nx + ny * ny)
    rv_dot = rx * vx + ry * vy + rz * vz
    # 偏心率矢量
    coef1 = v_mag * v_mag / MU_EARTH - 1.0 / r_mag
    coef2 = rv_dot / MU_EARTH
    ex = coef1 * rx - coef2 * vx
    ey = coef1 * ry - coef2 * vy
    ez = coef1 * rz - coef2 * vz
    e = math.sqrt(ex * ex + ey * ey + ez * ez)
    energy = v_mag * v_mag / 2 - MU_EARTH / r_mag
    a = -MU_EARTH / (2 * energy) if abs(energy) > 1e-12 else float("inf")
    i = math.degrees(math.acos(max(-1.0, min(1.0, hz / h_mag))))

    def clamp_acos(x: float) -> float:
        return math.degrees(math.acos(max(-1.0, min(1.0, x))))

    raan = clamp_acos(nx / n_mag) if n_mag > 1e-12 else 0.0
    if ny < 0:
        raan = 360.0 - raan
    if n_mag > 1e-12 and e > 1e-12:
        argp = clamp_acos((nx * ex + ny * ey) / (n_mag * e))
        if ez < 0:
            argp = 360.0 - argp
    else:
        argp = 0.0
    if e > 1e-12:
        nu = clamp_acos((ex * rx + ey * ry + ez * rz) / (e * r_mag))
        if rv_dot < 0:
            nu = 360.0 - nu
    else:
        nu = 0.0
    period = 2 * math.pi * math.sqrt(a**3 / MU_EARTH) if a > 0 else 0.0
    return {
        "a_m": a, "e": e, "i_deg": i, "raan_deg": raan, "argp_deg": argp, "nu_deg": nu,
        "period_s": period, "r_mag_m": r_mag, "v_mag_mps": v_mag,
        "alt_m": r_mag - RE_EARTH,
    }


def mean_to_true_deg(m_deg: float, e: float) -> float:
    """平近点角 -> 真近点角（牛顿迭代解开普勒方程）。"""
    m = math.radians(m_deg % 360.0)
    ecc_anom = m if e < 0.8 else math.pi
    for _ in range(30):
        delta = (ecc_anom - e * math.sin(ecc_anom) - m) / (1 - e * math.cos(ecc_anom))
        ecc_anom -= delta
        if abs(delta) < 1e-12:
            break
    nu = 2 * math.atan2(
        math.sqrt(1 + e) * math.sin(ecc_anom / 2),
        math.sqrt(1 - e) * math.cos(ecc_anom / 2),
    )
    return math.degrees(nu) % 360.0


def true_to_mean_deg(nu_deg: float, e: float) -> float:
    """真近点角 -> 平近点角。"""
    nu = math.radians(nu_deg % 360.0)
    ecc_anom = 2 * math.atan2(
        math.sqrt(1 - e) * math.sin(nu / 2),
        math.sqrt(1 + e) * math.cos(nu / 2),
    )
    m = ecc_anom - e * math.sin(ecc_anom)
    return math.degrees(m) % 360.0


def accel_twobody_j2(r: Vec3, enable_j2: bool = True) -> Vec3:
    """二体 + J2 摄动加速度。"""
    x, y, z = r
    r2 = x * x + y * y + z * z
    r_mag = math.sqrt(r2)
    if r_mag < 1.0:
        raise ValueError("位置矢量接近地心，状态无效")
    base = -MU_EARTH / (r2 * r_mag)
    ax, ay, az = base * x, base * y, base * z
    if enable_j2:
        k = 1.5 * J2_EARTH * MU_EARTH * RE_EARTH * RE_EARTH / (r2 * r2 * r_mag)
        zr2 = 5 * z * z / r2
        ax += k * x * (zr2 - 1)
        ay += k * y * (zr2 - 1)
        az += k * z * (zr2 - 3)
    return (ax, ay, az)


def rk4_step(state: State, dt: float, extra_accel: Vec3, enable_j2: bool) -> State:
    """RK4 单步积分：二体 + J2 + 外部加速度（推力等）。"""

    def deriv(s: State) -> State:
        ax, ay, az = accel_twobody_j2((s[0], s[1], s[2]), enable_j2)
        return (
            s[3], s[4], s[5],
            ax + extra_accel[0], ay + extra_accel[1], az + extra_accel[2],
        )

    def add_scaled(s: State, d: State, factor: float) -> State:
        return (
            s[0] + d[0] * factor, s[1] + d[1] * factor, s[2] + d[2] * factor,
            s[3] + d[3] * factor, s[4] + d[4] * factor, s[5] + d[5] * factor,
        )

    k1 = deriv(state)
    k2 = deriv(add_scaled(state, k1, dt / 2))
    k3 = deriv(add_scaled(state, k2, dt / 2))
    k4 = deriv(add_scaled(state, k3, dt))
    sixth = dt / 6
    return (
        state[0] + sixth * (k1[0] + 2 * k2[0] + 2 * k3[0] + k4[0]),
        state[1] + sixth * (k1[1] + 2 * k2[1] + 2 * k3[1] + k4[1]),
        state[2] + sixth * (k1[2] + 2 * k2[2] + 2 * k3[2] + k4[2]),
        state[3] + sixth * (k1[3] + 2 * k2[3] + 2 * k3[3] + k4[3]),
        state[4] + sixth * (k1[4] + 2 * k2[4] + 2 * k3[4] + k4[4]),
        state[5] + sixth * (k1[5] + 2 * k2[5] + 2 * k3[5] + k4[5]),
    )


def propagate(state: State, dt: float, extra_accel: Vec3 = (0.0, 0.0, 0.0),
              enable_j2: bool = True, max_substep: float = 10.0) -> State:
    """推进 dt 秒，自动细分子步保证精度。"""
    if dt == 0:
        return state
    n = max(1, math.ceil(abs(dt) / max_substep))
    h = dt / n
    s = state
    for _ in range(n):
        s = rk4_step(s, h, extra_accel, enable_j2)
    return s


def eci_to_geodetic(r: Vec3, gmst: float) -> dict[str, float]:
    """ECI -> 球面大地坐标（简化球形地球，用于态势显示星下点）。"""
    x, y, z = r
    # 绕 z 轴旋转 -gmst 到 ECEF
    cg, sg = math.cos(gmst), math.sin(gmst)
    xe = cg * x + sg * y
    ye = -sg * x + cg * y
    r_mag = math.sqrt(x * x + y * y + z * z)
    lon = math.degrees(math.atan2(ye, xe))
    lat = math.degrees(math.asin(max(-1.0, min(1.0, z / r_mag))))
    return {"lat_deg": lat, "lon_deg": lon, "alt_m": r_mag - RE_EARTH}
