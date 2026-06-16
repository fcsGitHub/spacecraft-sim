"""录制与回放数据测试。"""

import pytest

from simcore import (
    Recorder,
    SimulationEngine,
    delete_recording,
    list_recordings,
    load_recording,
    scenario_from_dict,
)
from simcore.recorder import RecorderError
from tests.conftest import make_scenario_dict


@pytest.fixture
def engine_and_recorder():
    scenario = scenario_from_dict(make_scenario_dict(
        sim={"epoch": "2026-06-12T04:00:00Z", "duration": 60, "step": 1, "seed": 7, "record": True},
    ))
    engine = SimulationEngine(scenario)
    engine.init()
    recorder = Recorder(scenario=scenario, run_id="test_run_001")
    return engine, recorder


class TestRecorder:
    def test_records_frames_and_events(self, engine_and_recorder):
        engine, recorder = engine_and_recorder
        recorder.on_frame(engine.last_frame)
        while not engine.finished:
            recorder.on_frame(engine.step())
        assert recorder.frames[0]["t"] == 0.0
        assert recorder.frames[-1]["t"] == pytest.approx(60.0)
        # duration=60, 间隔 max(1, 60/1500)=1 → 61 帧
        assert len(recorder.frames) == 61
        assert "SAT-01" in recorder.frames[0]["entities"]

    def test_save_load_roundtrip(self, engine_and_recorder, tmp_path):
        engine, recorder = engine_and_recorder
        for _ in range(10):
            recorder.on_frame(engine.step())
        path = recorder.save(tmp_path)
        assert path.exists()
        data = load_recording(tmp_path, "test_run_001")
        assert data["scenario_name"] == "测试场景"
        assert data["frame_count"] == len(data["frames"])
        listing = list_recordings(tmp_path)
        assert listing[0]["run_id"] == "test_run_001"
        delete_recording(tmp_path, "test_run_001")
        assert list_recordings(tmp_path) == []

    def test_path_traversal_rejected(self, tmp_path):
        with pytest.raises(RecorderError):
            load_recording(tmp_path, "../evil")

    def test_missing_recording(self, tmp_path):
        with pytest.raises(RecorderError):
            load_recording(tmp_path, "nope")


class TestRecordingMeta:
    """meta 旁车文件：列表接口免于解析全量帧数据。"""

    def test_save_writes_meta_sidecar(self, engine_and_recorder, tmp_path):
        engine, recorder = engine_and_recorder
        for _ in range(5):
            recorder.on_frame(engine.step())
        recorder.save(tmp_path)
        assert (tmp_path / "test_run_001.meta.json").is_file()
        listing = list_recordings(tmp_path)
        assert len(listing) == 1
        assert listing[0]["frame_count"] == len(recorder.frames)
        assert listing[0]["scenario_name"] == "测试场景"

    def test_legacy_recording_without_meta_backfills(self, engine_and_recorder, tmp_path):
        engine, recorder = engine_and_recorder
        for _ in range(5):
            recorder.on_frame(engine.step())
        recorder.save(tmp_path)
        meta = tmp_path / "test_run_001.meta.json"
        meta.unlink()  # 模拟旧版录制
        listing = list_recordings(tmp_path)
        assert listing[0]["run_id"] == "test_run_001"
        assert meta.is_file()  # 列表时自动回填

    def test_delete_removes_meta_too(self, engine_and_recorder, tmp_path):
        engine, recorder = engine_and_recorder
        recorder.on_frame(engine.step())
        recorder.save(tmp_path)
        delete_recording(tmp_path, "test_run_001")
        assert list(tmp_path.glob("*.json")) == []

    def test_meta_file_not_listed_as_recording(self, engine_and_recorder, tmp_path):
        engine, recorder = engine_and_recorder
        recorder.on_frame(engine.step())
        recorder.save(tmp_path)
        listing = list_recordings(tmp_path)
        assert len(listing) == 1  # meta 旁车不重复出现在清单
