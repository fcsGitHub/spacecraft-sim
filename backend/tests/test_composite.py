from simcore.bus import BusMessage
from simcore.composite import CompositeModel, Mount, build_satellite
from simcore.model import AtomicModel, SimContext
from simcore.params import ParamAttribute, ParamMROutput, ParamRTInput, ParamRTOutput, StepResult
from simcore.registry import discover_builtin_models, register_model
from simcore.scenario import scenario_from_dict

discover_builtin_models()


@register_model
class _Echo(AtomicModel):
    """把收到的订阅消息计数写入输出，便于断言过滤与顺序。"""
    model_type = "test.echo"
    subscribes = ("topic.in",)

    def __init__(self) -> None:
        super().__init__()
        self.tag = "x"

    def sim_init(self, ctx, bjt, utc, attribute) -> int:
        super().sim_init(ctx, bjt, utc, attribute)
        self.tag = str(dict(attribute.data).get("tag", "x"))
        return 0

    def sim_advance(self, ctx, bjt, utc, step, rt_in) -> StepResult:
        data = {f"seen_{self.tag}": len(rt_in.messages), f"up_{self.tag}": True}
        return StepResult(rt_output=ParamRTOutput(data=data),
                          mr_output=ParamMROutput(state={"tag": self.tag}))


def _ctx():
    class _Eng:
        class clock:
            t = 0.0
    return SimContext(engine=_Eng(), entity_id="E1", component="")


def test_advance_order_and_upstream_merge():
    comp = CompositeModel([
        Mount("a", _Echo(), {"tag": "a"}),
        Mount("b", _Echo(), {"tag": "b"}),
    ])
    comp.sim_init(_ctx(), (0,) * 6, (0,) * 6, ParamAttribute())
    res = comp.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                           ParamRTInput(upstream={"id": "E1"}))
    # 上游合并：两个子输出都进入实体态
    assert res.rt_output.data["up_a"] is True
    assert res.rt_output.data["up_b"] is True
    assert res.rt_output.data["id"] == "E1"


def test_message_filtered_per_child_subscription():
    comp = CompositeModel([Mount("a", _Echo(), {"tag": "a"})])
    comp.sim_init(_ctx(), (0,) * 6, (0,) * 6, ParamAttribute())
    msgs = (BusMessage(topic="topic.in"), BusMessage(topic="other"))
    res = comp.sim_advance(_ctx(), (0,) * 6, (0,) * 6, 1.0,
                           ParamRTInput(messages=msgs))
    assert res.rt_output.data["seen_a"] == 1  # 只看到订阅的 topic.in


def test_all_subscribes_union_and_component_names():
    comp = CompositeModel([Mount("a", _Echo(), {}), Mount("b", _Echo(), {})])
    assert comp.all_subscribes() == {"topic.in"}
    assert comp.component_names() == ["a", "b"]
    assert comp.has_component("a") is True
    assert comp.has_component("zzz") is False


def test_ctr_routes_to_named_child():
    seen = {}

    @register_model
    class _Cmd(AtomicModel):
        model_type = "test.cmd"

        def sim_ctr_response(self, ctr_in) -> int:
            seen[ctr_in.name] = ctr_in.entity_id
            return 0

        def sim_advance(self, ctx, bjt, utc, step, rt_in) -> StepResult:
            return StepResult()

    from simcore.params import ParamCtrInput
    comp = CompositeModel([Mount("c", _Cmd(), {})])
    comp.sim_init(_ctx(), (0,) * 6, (0,) * 6, ParamAttribute())
    comp.sim_ctr_response(ParamCtrInput(entity_id="E1", target_model="c", name="go"))
    assert seen["go"] == "E1"


def test_build_satellite_default_chain():
    scn = scenario_from_dict({
        "meta": {"name": "t"},
        "sim": {"epoch": "2026-01-01T00:00:00Z", "duration": 60, "step": 1, "seed": 1},
        "satellites": [{
            "id": "SAT-01", "name": "obs", "mass": 500, "fuel": 80,
            "payload": {"type": "光学成像", "state": "待机", "power": 300},
            "orbit": {"a": 7000, "e": 0.001, "i": 53, "raan": 10, "argp": 20, "M0": 30},
        }],
    })
    model = build_satellite(scn.satellites[0])
    assert model.component_names() == ["thruster", "orbit", "attitude", "payload"]
