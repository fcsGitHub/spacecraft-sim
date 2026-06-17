import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from simcore import discover_builtin_models  # noqa: E402

discover_builtin_models()


def make_scenario_dict(**overrides):
    """双星测试场景（与前端默认场景同构）。"""
    data = {
        "meta": {
            "name": "测试场景",
            "version": "1.0.0",
            "author": "pytest",
            "created": "2026-06-12",
            "description": "单元测试用例场景",
        },
        "sim": {
            "epoch": "2026-06-12T04:00:00Z",
            "duration": 600,
            "step": 1,
            "seed": 42,
            "record": True,
        },
        "satellites": [
            {
                "id": "SAT-01", "name": "测试星1", "group": "观测星组", "faction": "红方",
                "mass": 1000, "fuel": 80,
                "payload": {"type": "光学成像", "state": "待机", "power": 320},
                "orbit": {"a": 6878, "e": 0.001, "i": 97.5, "raan": 60, "argp": 90, "M0": 0},
            },
            {
                "id": "SAT-02", "name": "测试星2", "group": "观测星组", "faction": "蓝方",
                "mass": 1200, "fuel": 90,
                "payload": {"type": "合成孔径雷达", "state": "待机", "power": 450},
                "orbit": {"a": 6878, "e": 0.001, "i": 97.5, "raan": 60, "argp": 90, "M0": 40},
            },
        ],
        "groundStations": [
            {"id": "GS-01", "name": "北京站", "lat": 40.1, "lon": 116.3},
        ],
        "events": [],
    }
    data.update(overrides)
    return data


@pytest.fixture
def scenario_dict():
    return make_scenario_dict()
