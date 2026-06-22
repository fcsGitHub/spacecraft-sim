from simcore import SimulationEngine, scenario_from_dict
from simcore.params import EntityInfo
from simcore.registry import discover_builtin_models

discover_builtin_models()


def test_entityinfo_parent_default_empty():
    assert EntityInfo().parent == ""


def test_entityinfo_parent_set():
    assert EntityInfo(entity_id="C", parent="M").parent == "M"


def _mother_child_scn():
    return scenario_from_dict({
        "meta": {"name": "mc"},
        "sim": {"epoch": "2026-01-01T00:00:00Z", "duration": 60, "step": 1, "seed": 3},
        "satellites": [{
            "id": "MOTHER", "name": "母星", "mass": 800, "fuel": 90,
            "payload": {"type": "光学成像", "state": "待机", "power": 300},
            "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 0},
            "children": [{
                "id": "CHILD", "name": "子星", "mass": 120, "fuel": 100,
                "payload": {"type": "电子侦察", "state": "待机", "power": 80},
                "orbit": {"a": 7100, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 30},
            }],
        }],
    })


def test_mother_and_child_are_top_level_entities():
    eng = SimulationEngine(_mother_child_scn())
    eng.init()
    infos = {e["id"]: e for e in eng.entity_infos()}
    assert set(infos) == {"MOTHER", "CHILD"}
    assert infos["MOTHER"]["parent"] == ""
    assert infos["CHILD"]["parent"] == "MOTHER"


def test_child_has_independent_position():
    eng = SimulationEngine(_mother_child_scn())
    eng.init()
    eng.step()
    ents = eng.last_frame.entities
    assert "pos_km" in ents["CHILD"]
    assert ents["CHILD"]["pos_km"] != ents["MOTHER"]["pos_km"]


def test_children_deterministic():
    e1 = SimulationEngine(_mother_child_scn()); e1.init()
    e2 = SimulationEngine(_mother_child_scn()); e2.init()
    for _ in range(15):
        f1, f2 = e1.step(), e2.step()
    assert f1.entities["CHILD"]["pos_km"] == f2.entities["CHILD"]["pos_km"]
