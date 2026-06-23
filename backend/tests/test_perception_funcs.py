# backend/tests/test_perception_funcs.py
from simcore.perception import (
    merge_perception, is_god, visible_entities, filter_events, faction_view, fog_recording,
)


def test_is_god():
    assert is_god(None) and is_god("") and is_god("全局") and is_god("中立")
    assert not is_god("红方")


def test_merge_prefers_freshest_age():
    delayed = {"红方": {"B1": {"pos_km": [1, 0, 0], "source": "delayed", "age_s": 30.0}}}
    onboard = {"红方": {"B1": {"pos_km": [2, 0, 0], "source": "onboard", "age_s": 0.0,
                              "observers": ["R1"]}}}
    merged = merge_perception([delayed, onboard])
    assert merged["红方"]["B1"]["source"] == "onboard"
    assert merged["红方"]["B1"]["pos_km"] == [2, 0, 0]


def test_merge_unions_observers_on_tie():
    a = {"红方": {"B1": {"pos_km": [1, 0, 0], "source": "onboard", "age_s": 0.0,
                        "observers": ["R1"]}}}
    b = {"红方": {"B1": {"pos_km": [1, 0, 0], "source": "onboard", "age_s": 0.0,
                        "observers": ["R2"]}}}
    merged = merge_perception([a, b])
    assert sorted(merged["红方"]["B1"]["observers"]) == ["R1", "R2"]


def _frame():
    return {
        "t": 1.0, "utc": "x",
        "entities": {
            "R1": {"id": "R1", "name": "红1", "faction": "红方", "pos_km": [1, 0, 0]},
            "B1": {"id": "B1", "name": "蓝1", "faction": "蓝方", "pos_km": [2, 0, 0]},
            "B2": {"id": "B2", "name": "蓝2", "faction": "蓝方", "pos_km": [3, 0, 0]},
        },
        "perception": {"红方": {"B1": {"pos_km": [2, 0, 0], "source": "onboard", "age_s": 0.0}}},
        "events": [{"t": 1.0, "target": "B2", "text": "蓝2事件"},
                   {"t": 1.0, "target": "R1", "text": "红1事件"},
                   {"t": 1.0, "target": "", "text": "系统事件"}],
    }


def test_visible_entities_god_sees_all():
    vis = visible_entities(_frame(), "全局")
    assert set(vis) == {"R1", "B1", "B2"}


def test_visible_entities_faction_own_plus_sensed():
    vis = visible_entities(_frame(), "红方")
    assert set(vis) == {"R1", "B1"}            # 己方 R1 + 已感知 B1；未感知 B2 隐藏
    assert vis["B1"]["source"] == "onboard"     # 感知态保留来源
    assert vis["B1"]["name"] == "蓝1"           # 身份揭示


def test_filter_events_by_visibility():
    vis_ids = {"R1", "B1"}
    evs = filter_events(_frame()["events"], vis_ids)
    texts = {e["text"] for e in evs}
    assert texts == {"红1事件", "系统事件"}      # B2 事件被滤除，空 target 放行


def test_faction_view_strips_perception():
    view = faction_view(_frame(), "红方")
    assert "perception" not in view
    assert set(view["entities"]) == {"R1", "B1"}
    assert {e["text"] for e in view["events"]} == {"红1事件", "系统事件"}


def test_faction_view_god_keeps_all_strips_perception():
    view = faction_view(_frame(), "全局")
    assert set(view["entities"]) == {"R1", "B1", "B2"}
    assert "perception" not in view


def test_fog_recording_filters_frames_and_events():
    rec = {"frames": [_frame()], "events": [
        {"t": 1.0, "target": "B2", "text": "蓝2"},
        {"t": 1.0, "target": "B1", "text": "蓝1曾被感知"},
        {"t": 1.0, "target": "R1", "text": "红1"},
    ]}
    fogged = fog_recording(rec, "红方")
    assert set(fogged["frames"][0]["entities"]) == {"R1", "B1"}
    texts = {e["text"] for e in fogged["events"]}
    assert texts == {"红1", "蓝1曾被感知"}        # B1 曾被感知 → 保留；B2 从未可见 → 滤除
    assert fog_recording(rec, "全局") is rec       # god 视图原样返回
