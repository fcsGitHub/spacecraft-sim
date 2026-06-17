"""场景加载与校验测试。"""

import json

import pytest
import yaml

from simcore import ScenarioError, load_scenario, scenario_from_dict, validate_scenario
from tests.conftest import make_scenario_dict


class TestValidation:
    def test_valid_scenario_passes(self, scenario_dict):
        errors, warnings = validate_scenario(scenario_dict)
        assert errors == []
        assert warnings == []

    def test_missing_name(self, scenario_dict):
        scenario_dict["meta"]["name"] = ""
        errors, _ = validate_scenario(scenario_dict)
        assert any("名称" in e["msg"] for e in errors)

    def test_duplicate_sat_id(self, scenario_dict):
        scenario_dict["satellites"][1]["id"] = "SAT-01"
        errors, _ = validate_scenario(scenario_dict)
        assert any("重复" in e["msg"] for e in errors)

    def test_low_perigee_rejected(self, scenario_dict):
        scenario_dict["satellites"][0]["orbit"]["a"] = 6878
        scenario_dict["satellites"][0]["orbit"]["e"] = 0.1
        errors, _ = validate_scenario(scenario_dict)
        assert any("再入" in e["msg"] for e in errors)

    def test_event_unknown_target(self, scenario_dict):
        scenario_dict["events"] = [{"t": 10, "type": "机动", "target": "NOPE", "action": "x"}]
        errors, _ = validate_scenario(scenario_dict)
        assert any("不存在" in e["msg"] for e in errors)

    def test_event_time_out_of_range(self, scenario_dict):
        scenario_dict["events"] = [{"t": 999999, "type": "机动", "target": "SAT-01", "action": "x"}]
        errors, _ = validate_scenario(scenario_dict)
        assert any("超出" in e["msg"] for e in errors)

    def test_low_fuel_warning(self, scenario_dict):
        scenario_dict["satellites"][0]["fuel"] = 10
        errors, warnings = validate_scenario(scenario_dict)
        assert errors == []
        assert any("燃料" in w["msg"] for w in warnings)

    def test_non_integer_seed(self, scenario_dict):
        scenario_dict["sim"]["seed"] = 1.5
        errors, _ = validate_scenario(scenario_dict)
        assert any("种子" in e["msg"] for e in errors)

    def test_unknown_faction_warns_not_errors(self, scenario_dict):
        scenario_dict["satellites"][0]["faction"] = "紫方"
        errors, warnings = validate_scenario(scenario_dict)
        assert errors == []
        assert any("阵营" in w["msg"] for w in warnings)

    def test_missing_faction_is_allowed(self, scenario_dict):
        del scenario_dict["satellites"][0]["faction"]
        errors, warnings = validate_scenario(scenario_dict)
        assert errors == []
        assert warnings == []

    def test_invalid_epoch(self, scenario_dict):
        scenario_dict["sim"]["epoch"] = "not-a-date"
        errors, _ = validate_scenario(scenario_dict)
        assert any("历元" in e["msg"] for e in errors)


class TestLoading:
    def test_from_dict(self, scenario_dict):
        sc = scenario_from_dict(scenario_dict)
        assert sc.name == "测试场景"
        assert sc.seed == 42
        assert len(sc.satellites) == 2
        assert sc.satellites[0].orbit.a == 6878
        assert sc.ground_stations[0].name == "北京站"

    def test_faction_parsed_and_defaults_empty(self, scenario_dict):
        del scenario_dict["satellites"][1]["faction"]
        sc = scenario_from_dict(scenario_dict)
        assert sc.satellites[0].faction == "红方"
        assert sc.satellites[1].faction == ""  # 缺省为空

    def test_from_json_text(self, scenario_dict):
        sc = load_scenario(json.dumps(scenario_dict, ensure_ascii=False))
        assert sc.name == "测试场景"

    def test_from_yaml_text(self, scenario_dict):
        sc = load_scenario(yaml.safe_dump(scenario_dict, allow_unicode=True))
        assert sc.name == "测试场景"
        assert sc.step_s == 1.0

    def test_invalid_raises_with_all_errors(self, scenario_dict):
        scenario_dict["meta"]["name"] = ""
        scenario_dict["satellites"][0]["fuel"] = -5
        with pytest.raises(ScenarioError) as exc_info:
            scenario_from_dict(scenario_dict)
        assert len(exc_info.value.errors) >= 2

    def test_events_sorted_by_time(self, scenario_dict):
        scenario_dict["events"] = [
            {"t": 300, "type": "载荷", "target": "SAT-01", "action": "开机"},
            {"t": 100, "type": "机动", "target": "SAT-02", "action": "Δv=1 m/s"},
        ]
        sc = scenario_from_dict(scenario_dict)
        assert [e.t for e in sc.events] == [100, 300]

    def test_empty_text_rejected(self):
        with pytest.raises(ScenarioError):
            load_scenario("  ")

    def test_bad_json_rejected(self):
        with pytest.raises(ScenarioError):
            load_scenario("{broken json", fmt="json")
