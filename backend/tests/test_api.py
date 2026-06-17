"""服务端 API 集成测试。"""

import json
import os
import tempfile

# 数据目录隔离：必须在导入 server.main 之前设置
os.environ["SCSIM_DATA_DIR"] = tempfile.mkdtemp(prefix="scsim_test_")

import pytest
from fastapi.testclient import TestClient

from server.main import app
from tests.conftest import make_scenario_dict


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def short_scenario():
    return make_scenario_dict(
        sim={"epoch": "2026-06-12T04:00:00Z", "duration": 30, "step": 1, "seed": 9, "record": True},
    )


class TestBasics:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_models_registered(self, client):
        r = client.get("/api/models")
        types = [m["model_type"] for m in r.json()]
        assert {"orbit.j2", "prop.thruster", "aocs.simple", "payload.generic"} <= set(types)


class TestScenarioApi:
    def test_get_default_scenario(self, client):
        r = client.get("/api/scenario")
        body = r.json()
        assert body["data"]["meta"]["name"]
        assert body["errors"] == []

    def test_put_draft_allows_invalid(self, client, short_scenario):
        short_scenario["satellites"][0]["fuel"] = -1
        r = client.put("/api/scenario", json=short_scenario)
        assert r.status_code == 200
        assert r.json()["saved"] is True
        assert len(r.json()["errors"]) > 0

    def test_put_rejects_malformed(self, client):
        r = client.put("/api/scenario", json={"foo": 1})
        assert r.status_code == 400

    def test_import_yaml(self, client, short_scenario):
        import yaml

        text = yaml.safe_dump(short_scenario, allow_unicode=True)
        r = client.post("/api/scenario/import", json={"text": text, "fmt": "yaml"})
        assert r.status_code == 200
        assert r.json()["name"] == "测试场景"

    def test_import_invalid_rejected(self, client, short_scenario):
        short_scenario["satellites"] = []
        r = client.post("/api/scenario/import",
                        json={"text": json.dumps(short_scenario), "fmt": "json"})
        assert r.status_code == 400

    def test_export_yaml(self, client):
        r = client.get("/api/scenario/export", params={"fmt": "yaml"})
        assert r.status_code == 200
        assert "meta:" in r.text


class TestSimulationApi:
    def test_full_control_flow(self, client, short_scenario):
        # 装载
        r = client.post("/api/simulation/load", json=short_scenario)
        assert r.status_code == 200
        assert r.json()["state"] == "paused"
        assert r.json()["entity_count"] == 2

        # 单步推进
        r = client.post("/api/simulation/step", json={"dt": 5})
        assert r.status_code == 200
        assert r.json()["t"] == pytest.approx(5.0)

        # 指令注入（立即）
        r = client.post("/api/simulation/command", json={
            "tpl": "载荷控制", "target": "SAT-01",
            "params": {"act": "开机"}, "when": "now", "delay": 0,
        })
        assert r.status_code == 200
        assert r.json()["accepted"] is True

        # 指令注入（定时）
        r = client.post("/api/simulation/command", json={
            "tpl": "轨道机动", "target": "SAT-02",
            "params": {"dv": 1.0, "dir": "切向"}, "when": "later", "delay": 10,
        })
        assert r.status_code == 200
        assert r.json()["command"]["t"] == pytest.approx(15.0)

        r = client.get("/api/simulation/commands")
        cmds = r.json()
        assert len(cmds) == 2
        assert cmds[0]["fired"] is True
        assert cmds[1]["fired"] is False

        # 倍速与门限
        assert client.post("/api/simulation/speed", json={"speed": 300}).status_code == 200
        assert client.post("/api/simulation/alert-threshold", json={"km": 50}).status_code == 200

        # 推到结束 → 录制落盘
        r = client.post("/api/simulation/step", json={"dt": 30})
        assert r.json()["state"] == "finished"
        rec_id = r.json()["last_recording_id"]
        assert rec_id

        # 回放
        r = client.get("/api/replays")
        assert any(item["run_id"] == rec_id for item in r.json())
        r = client.get(f"/api/replays/{rec_id}")
        body = r.json()
        assert body["frame_count"] > 0
        assert body["frames"][0]["entities"]["SAT-01"]["pos_km"]
        # 删除
        assert client.delete(f"/api/replays/{rec_id}").status_code == 200

        # 复位
        r = client.post("/api/simulation/reset")
        assert r.json()["t"] == 0.0
        assert r.json()["state"] == "paused"

    def test_command_out_of_range_rejected(self, client, short_scenario):
        client.post("/api/simulation/load", json=short_scenario)
        r = client.post("/api/simulation/command", json={
            "tpl": "载荷控制", "target": "SAT-01",
            "params": {"act": "开机"}, "when": "later", "delay": 99999,
        })
        assert r.status_code == 400

    def test_load_invalid_scenario_rejected(self, client, short_scenario):
        short_scenario["satellites"] = []
        r = client.post("/api/simulation/load", json=short_scenario)
        assert r.status_code == 400
        assert "errors" in r.json()["detail"]

    def test_websocket_snapshot(self, client, short_scenario):
        client.post("/api/simulation/load", json=short_scenario)
        with client.websocket_connect("/ws/situation") as ws:
            first = ws.receive_json()
            assert first["type"] == "status"
            assert first["data"]["state"] == "paused"
            second = ws.receive_json()
            assert second["type"] == "frame"
            assert "SAT-01" in second["data"]["entities"]


class TestPredictApi:
    def test_predict_returns_tracks(self, client, short_scenario):
        client.post("/api/simulation/load", json=short_scenario)
        r = client.get("/api/simulation/predict", params={"horizon": 600, "step": 60})
        assert r.status_code == 200
        body = r.json()
        assert set(body["tracks"]) == {"SAT-01", "SAT-02"}
        assert len(body["tracks"]["SAT-01"]) == len(body["times"])
        assert body["step_used_s"] == pytest.approx(1.0)  # 短时长用引擎步长
        assert len(body["tracks"]["SAT-01"][0]["pos_km"]) == 3

    def test_predict_default_one_day_coarsens(self, client, short_scenario):
        client.post("/api/simulation/load", json=short_scenario)
        r = client.get("/api/simulation/predict")  # 默认 86400s
        assert r.status_code == 200
        assert r.json()["horizon_s"] == pytest.approx(86400.0)
        assert r.json()["step_used_s"] > 1.0

    def test_predict_rejects_bad_horizon(self, client, short_scenario):
        client.post("/api/simulation/load", json=short_scenario)
        r = client.get("/api/simulation/predict", params={"horizon": 0})
        assert r.status_code == 409


class TestExternalApi:
    def test_get_config(self, client):
        r = client.get("/api/external/config")
        body = r.json()
        assert any(cat["id"] == "feed" for cat in body["categories"])

    def test_test_local_file_system(self, client):
        r = client.post("/api/external/test/data-exp")
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "warn")

    def test_test_unknown_system(self, client):
        assert client.post("/api/external/test/nope").status_code == 404

    def test_test_disabled_system_rejected(self, client):
        assert client.post("/api/external/test/viz-wall").status_code == 409

    def test_test_unreachable_endpoint(self, client):
        config = client.get("/api/external/config").json()
        for cat in config["categories"]:
            for sys_ in cat["systems"]:
                if sys_["id"] == "eng-att":
                    sys_["enabled"] = True
                    sys_["endpoint"] = "127.0.0.1:1"  # 几乎必然拒绝
                    sys_["timeout"] = 300
        client.put("/api/external/config", json=config)
        r = client.post("/api/external/test/eng-att")
        assert r.json()["status"] == "danger"

    def test_snapshot_and_rollback(self, client):
        r = client.post("/api/external/snapshots", json={"note": "测试快照"})
        tag = r.json()["tag"]
        assert r.json()["current"] is True
        r = client.post("/api/external/rollback", json={"tag": tag})
        assert r.json()["version"] == tag
        assert client.post("/api/external/rollback", json={"tag": "v99.9"}).status_code == 404
