"""仿真时间基准：UTC / BJT(北京时, UTC+8) 历元管理。

规范要求模型接口接收 bjt[6] 与 utc[6]（年 月 日 时 分 秒）。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

BJT = timezone(timedelta(hours=8), name="BJT")

# 地球自转角速率（GMST 简化式对时间的导数，rad/s）。
# gmst_rad 对时间严格线性，故 gmst(epoch+t) == gmst(epoch) + 该速率×t（模 2π），
# 模型可据此用历元 GMST 线性递推，避免每步构造 datetime。
OMEGA_EARTH_RAD_PER_S = math.radians(360.98564736629 / 86400.0)


def datetime_to_array6(dt: datetime) -> tuple[float, float, float, float, float, float]:
    """datetime -> (年, 月, 日, 时, 分, 秒)，秒含小数部分。"""
    return (
        float(dt.year),
        float(dt.month),
        float(dt.day),
        float(dt.hour),
        float(dt.minute),
        dt.second + dt.microsecond / 1e6,
    )


def parse_epoch(value: str) -> datetime:
    """解析 ISO8601 历元字符串为 UTC datetime，无时区信息时按 UTC 处理。"""
    text = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class SimClock:
    """不可变仿真时钟：epoch + 已推进秒数。每次推进返回新对象。"""

    epoch_utc: datetime
    t: float = 0.0

    def advanced(self, step: float) -> "SimClock":
        return SimClock(epoch_utc=self.epoch_utc, t=self.t + step)

    @property
    def utc(self) -> datetime:
        return self.epoch_utc + timedelta(seconds=self.t)

    @property
    def bjt(self) -> datetime:
        return self.utc.astimezone(BJT)

    @property
    def utc_array(self) -> tuple[float, float, float, float, float, float]:
        return datetime_to_array6(self.utc)

    @property
    def bjt_array(self) -> tuple[float, float, float, float, float, float]:
        return datetime_to_array6(self.bjt)

    @property
    def utc_iso(self) -> str:
        return self.utc.isoformat().replace("+00:00", "Z")


def gmst_rad(utc: datetime) -> float:
    """格林尼治平恒星时（简化算法，用于 ECI->ECEF 经纬度换算，精度满足态势显示）。"""
    # 参考 Vallado 简化式：以 J2000.0 起算的儒略世纪数
    j2000 = datetime(2000, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    d = (utc - j2000).total_seconds() / 86400.0
    gmst_deg = (280.46061837 + 360.98564736629 * d) % 360.0
    return math.radians(gmst_deg)
