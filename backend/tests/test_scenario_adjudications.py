from simcore.registry import discover_builtin_models
from simcore.scenario import scenario_from_dict, validate_scenario

discover_builtin_models()


def _base(adj):
    return {
        "meta": {"name": "t"},
        "sim": {"epoch": "2026-01-01T00:00:00Z", "duration": 60, "step": 1, "seed": 1},
        "satellites": [{
            "id": "SAT-01", "name": "obs", "mass": 500, "fuel": 80,
            "payload": {"type": "光学成像", "state": "待机", "power": 300},
            "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 0, "argp": 0, "M0": 0},
        }],
        "adjudications": adj,
    }


def test_valid_adjudication_passes():
    errors, _ = validate_scenario(_base([{"type": "adjud.photo"}]))
    assert errors == []


def test_unknown_type_errors():
    errors, _ = validate_scenario(_base([{"type": "nope.nope"}]))
    assert any("nope.nope" in e["msg"] for e in errors)


def test_non_adjudication_kind_errors():
    # orbit.j2 是 atomic，不是 adjudication
    errors, _ = validate_scenario(_base([{"type": "orbit.j2"}]))
    assert any("裁决" in e["msg"] for e in errors)


def test_adjudications_must_be_list():
    errors, _ = validate_scenario(_base({"type": "adjud.photo"}))
    assert any("adjudications" in e["loc"] or "裁决" in e["loc"] for e in errors)


def test_scenario_from_dict_parses_adjudications():
    scn = scenario_from_dict(_base([{"type": "adjud.photo"},
                                    {"type": "adjud.proximity", "params": {"threshold_km": 50}}]))
    assert [a.type for a in scn.adjudications] == ["adjud.photo", "adjud.proximity"]
    assert scn.adjudications[1].params["threshold_km"] == 50
