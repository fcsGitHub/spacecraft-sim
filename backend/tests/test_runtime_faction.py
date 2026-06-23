# backend/tests/test_runtime_faction.py
import asyncio
import json

from server.runtime import SimulationRunner


class FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(text)


def _frame():
    return {
        "t": 1.0, "utc": "x",
        "entities": {
            "R1": {"id": "R1", "faction": "红方", "pos_km": [1, 0, 0]},
            "B1": {"id": "B1", "faction": "蓝方", "pos_km": [2, 0, 0]},
            "B2": {"id": "B2", "faction": "蓝方", "pos_km": [9, 0, 0]},
        },
        "perception": {"红方": {"B1": {"pos_km": [2, 0, 0], "source": "onboard", "age_s": 0.0}}},
        "events": [],
    }


def test_per_faction_dispatch_fogs(tmp_path):
    r = SimulationRunner(str(tmp_path))
    god, red = FakeWS(), FakeWS()
    r.attach(god)                      # 默认 "" = 全局
    r.attach(red)
    r.set_faction(red, "红方")
    asyncio.run(r._send_frame_per_faction(_frame(), [], "running"))
    god_msg = json.loads(god.sent[-1])
    red_msg = json.loads(red.sent[-1])
    assert set(god_msg["data"]["entities"]) == {"R1", "B1", "B2"}     # 全局见全部
    assert set(red_msg["data"]["entities"]) == {"R1", "B1"}           # 红方见己方+已感知，B2 隐藏
    assert "perception" not in red_msg["data"]


def test_events_fogged_per_faction(tmp_path):
    r = SimulationRunner(str(tmp_path))
    red = FakeWS()
    r.attach(red)
    r.set_faction(red, "红方")
    events = [{"t": 1.0, "target": "B2", "text": "蓝2事件"},
              {"t": 1.0, "target": "R1", "text": "红1事件"}]
    asyncio.run(r._send_frame_per_faction(_frame(), events, "running"))
    red_msg = json.loads(red.sent[-1])
    assert [e["text"] for e in red_msg["events"]] == ["红1事件"]      # B2 不可见 → 事件滤除
