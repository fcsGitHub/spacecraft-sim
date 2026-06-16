"""指令模板 / 预设事件翻译测试。"""

import pytest

from simcore import TranslateError, command_from_event, command_from_template
from simcore.scenario import EventDef


class TestTemplates:
    def test_maneuver(self):
        cmd = command_from_template("轨道机动", "SAT-06", {"dv": 2.0, "dir": "法向"}, t=100)
        assert cmd.name == "maneuver"
        assert cmd.target_model == "thruster"
        assert cmd.params == {"dv_mps": 2.0, "dir": "法向"}
        assert cmd.ev_type == "机动"

    def test_payload(self):
        cmd = command_from_template("载荷控制", "SAT-01", {"act": "关机"}, t=0)
        assert cmd.name == "payload_ctrl"
        assert cmd.params["act"] == "关机"

    def test_attitude(self):
        cmd = command_from_template("姿态调整", "SAT-01", {"att": "目标跟瞄"}, t=0)
        assert cmd.params["mode"] == "目标跟瞄"

    def test_formation(self):
        cmd = command_from_template("编队保持", "SAT-02", {"ref": "SAT-01", "dist": 25}, t=0)
        assert cmd.name == "formation_keep"
        assert cmd.params == {"ref_id": "SAT-01", "dist_km": 25.0}

    def test_unknown_template(self):
        with pytest.raises(TranslateError):
            command_from_template("自毁", "SAT-01", {}, t=0)

    def test_unknown_direction(self):
        with pytest.raises(TranslateError):
            command_from_template("轨道机动", "SAT-01", {"dv": 1, "dir": "斜向"}, t=0)


class TestEvents:
    def test_maneuver_text_parsing(self):
        ev = EventDef(t=1800, ev_type="机动", target="SAT-06", action="轨道机动 Δv=2.0 m/s 切向")
        cmd = command_from_event(ev)
        assert cmd is not None
        assert cmd.params["dv_mps"] == 2.0
        assert cmd.params["dir"] == "切向"
        assert cmd.source == "event"

    def test_maneuver_normal_direction(self):
        ev = EventDef(t=3600, ev_type="机动", target="SAT-06", action="轨道机动 Δv=1.2 m/s 法向")
        cmd = command_from_event(ev)
        assert cmd.params["dir"] == "法向"

    def test_payload_off(self):
        ev = EventDef(t=5400, ev_type="载荷", target="SAT-02", action="光学载荷关机")
        cmd = command_from_event(ev)
        assert cmd.params["act"] == "关机"

    def test_payload_imaging(self):
        ev = EventDef(t=900, ev_type="载荷", target="SAT-03", action="SAR 条带成像")
        cmd = command_from_event(ev)
        assert cmd.params["act"] == "单次成像"

    def test_attitude_keyword(self):
        ev = EventDef(t=7200, ev_type="姿态", target="CHS-01", action="转交会对接姿态")
        cmd = command_from_event(ev)
        assert cmd.params["mode"] == "交会对接姿态"

    def test_system_fault(self):
        ev = EventDef(t=3600, ev_type="系统", target="WLK-05", action="模拟单星失效（调度重规划触发）")
        cmd = command_from_event(ev)
        assert cmd.channel == "dir"
        assert cmd.name == "fault"

    def test_system_plain_log(self):
        ev = EventDef(t=600, ev_type="系统", target="WLK-01", action="区域成像任务开始")
        cmd = command_from_event(ev)
        assert cmd.channel == "ctr"
        assert cmd.name == "log"
