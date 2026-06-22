from simcore.registry import discover_builtin_models
from simcore.scenario import scenario_from_dict, validate_scenario

discover_builtin_models()


def _node(sid, m0=0.0, children=None, **over):
    n = {
        "id": sid, "name": sid, "mass": 500, "fuel": 80,
        "payload": {"type": "光学成像", "state": "待机", "power": 300},
        "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": m0},
    }
    n.update(over)
    if children is not None:
        n["children"] = children
    return n


def _scn(sats):
    return {
        "meta": {"name": "t"},
        "sim": {"epoch": "2026-01-01T00:00:00Z", "duration": 60, "step": 1, "seed": 1},
        "satellites": sats,
    }


def test_children_flattened_with_parent():
    scn = scenario_from_dict(_scn([
        _node("MOTHER", children=[_node("CHILD-A", m0=10), _node("CHILD-B", m0=20)]),
    ]))
    by_id = {s.sat_id: s for s in scn.satellites}
    assert set(by_id) == {"MOTHER", "CHILD-A", "CHILD-B"}
    assert by_id["MOTHER"].parent == ""
    assert by_id["CHILD-A"].parent == "MOTHER"
    assert by_id["CHILD-B"].parent == "MOTHER"


def test_grandchild_parent_chain():
    scn = scenario_from_dict(_scn([
        _node("L1", children=[_node("L2", m0=5, children=[_node("L3", m0=9)])]),
    ]))
    by_id = {s.sat_id: s for s in scn.satellites}
    assert by_id["L2"].parent == "L1"
    assert by_id["L3"].parent == "L2"


def test_duplicate_id_across_tree_errors():
    errors, _ = validate_scenario(_scn([
        _node("DUP", children=[_node("DUP", m0=3)]),
    ]))
    assert any("DUP" in e["msg"] for e in errors)


def test_child_invalid_orbit_errors_with_child_loc():
    bad = _node("CHILD", m0=0)
    bad["orbit"]["a"] = 100  # 过小
    errors, _ = validate_scenario(_scn([_node("MOTHER", children=[bad])]))
    assert any(e["loc"] == "CHILD" for e in errors)


def test_children_must_be_list():
    n = _node("MOTHER")
    n["children"] = {"id": "X"}
    errors, _ = validate_scenario(_scn([n]))
    assert any("children" in e["msg"] for e in errors)


def test_depth_over_4_errors():
    scn = _scn([_node("L1", children=[
        _node("L2", m0=1, children=[
            _node("L3", m0=2, children=[
                _node("L4", m0=3, children=[_node("L5", m0=4)])])])])])
    errors, _ = validate_scenario(scn)
    assert any("嵌套" in e["msg"] for e in errors)


def test_event_target_child_id_valid():
    scn = _scn([_node("MOTHER", children=[_node("CHILD", m0=7)])])
    scn["events"] = [{"t": 10, "type": "载荷", "target": "CHILD", "action": "开机"}]
    errors, _ = validate_scenario(scn)
    assert not any("不存在" in e["msg"] for e in errors)


def test_child_components_parsed():
    scn = scenario_from_dict(_scn([
        _node("MOTHER", children=[
            _node("CHILD", m0=4, components=[
                {"name": "orbit", "model": "orbit.j2"},
                {"name": "camera", "model": "sensor.camera"}])]),
    ]))
    child = {s.sat_id: s for s in scn.satellites}["CHILD"]
    assert child.raw["components"][1]["model"] == "sensor.camera"
