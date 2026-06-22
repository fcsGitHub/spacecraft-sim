from simcore.bus import BusMessage
from simcore.params import ParamRTInput, StepResult


def test_rtinput_messages_defaults_empty():
    assert ParamRTInput().messages == ()


def test_rtinput_carries_messages():
    m = BusMessage(topic="camera.photo_result")
    rt = ParamRTInput(messages=(m,))
    assert rt.messages == (m,)


def test_stepresult_messages_defaults_empty():
    assert StepResult().messages == ()


def test_stepresult_carries_messages():
    m = BusMessage(topic="camera.photo_request")
    res = StepResult(messages=(m,))
    assert res.messages == (m,)
