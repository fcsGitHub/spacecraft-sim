# backend/tests/test_api_faction.py
import os
import tempfile

os.environ.setdefault("SCSIM_DATA_DIR", tempfile.mkdtemp(prefix="scsim_test_"))

from fastapi.testclient import TestClient

from server.main import app
from tests.conftest import make_scenario_dict


def _scn():
    # SAT-01 红方挂感知载荷 + 星上感知裁决；SAT-02 蓝方为目标
    data = make_scenario_dict(
        sim={"epoch": "2026-06-12T04:00:00Z", "duration": 30, "step": 1, "seed": 7, "record": True})
    data["satellites"][0]["components"] = [
        {"name": "thruster", "model": "prop.thruster"},
        {"name": "orbit", "model": "orbit.j2"},
        {"name": "attitude", "model": "aocs.simple"},
        {"name": "payload", "model": "payload.generic"},
        {"name": "sensor", "model": "sensor.perception", "params": {"max_range_km": 50, "state": "开机"}},
    ]
    data["adjudications"] = [{"type": "adjud.perception_onboard"}]
    return data


def test_ws_set_faction_fogs_frame():
    with TestClient(app) as c:
        c.post("/api/simulation/load", json=_scn())
        with c.websocket_connect("/ws/situation") as ws:
            # 默认全局：首帧应含两星
            while True:
                m = ws.receive_json()
                if m["type"] == "frame":
                    break
            assert set(m["data"]["entities"]) >= {"SAT-01", "SAT-02"}
            # 切红方：SAT-02 距离远（>50km 作用距离）未感知 → 应隐藏
            ws.send_json({"op": "set_faction", "faction": "红方"})
            frame = None
            for _ in range(5):
                m = ws.receive_json()
                if m["type"] == "frame":
                    frame = m
                    break
            assert "SAT-01" in frame["data"]["entities"]
            assert "SAT-02" not in frame["data"]["entities"]


def test_replay_faction_param_filters(tmp_path_factory):
    with TestClient(app) as c:
        c.post("/api/simulation/load", json=_scn())
        c.post("/api/simulation/start")
        # 跑到结束生成录制
        import time
        for _ in range(60):
            st = c.get("/api/simulation/status").json()
            if st["state"] == "finished":
                break
            time.sleep(0.1)
        listing = c.get("/api/replays").json()
        assert listing, "应已生成回放录制"
        rid = listing[0]["run_id"]
        full = c.get(f"/api/replays/{rid}").json()
        assert any("SAT-02" in f["entities"] for f in full["frames"])     # 全局含蓝方
        red = c.get(f"/api/replays/{rid}?faction=红方").json()
        assert all("SAT-02" not in f["entities"] for f in red["frames"])  # 红方迷雾隐藏未感知蓝方
