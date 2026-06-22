from simcore.model import AdjudicationModel, AtomicModel, SimModel
from simcore.params import StepResult


class _Leaf(AtomicModel):
    model_type = "test.leaf"
    subscribes = ("topic.x",)
    publishes = ("topic.y",)

    def sim_advance(self, ctx, bjt, utc, step, rt_in) -> StepResult:
        return StepResult()


class _Adj(AdjudicationModel):
    model_type = "test.adj"

    def sim_advance(self, ctx, bjt, utc, step, rt_in) -> StepResult:
        return StepResult()


def test_atomic_is_simmodel_with_kind():
    assert issubclass(AtomicModel, SimModel)
    assert _Leaf().model_kind == "atomic"


def test_adjudication_kind():
    assert issubclass(AdjudicationModel, SimModel)
    assert _Adj().model_kind == "adjudication"


def test_metadata_exposes_kind_and_topics():
    md = _Leaf.metadata()
    assert md["model_kind"] == "atomic"
    assert md["subscribes"] == ("topic.x",)
    assert md["publishes"] == ("topic.y",)
