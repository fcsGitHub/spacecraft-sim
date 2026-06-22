from simcore.bus import BusMessage, MessageBus


def test_stamp_assigns_source_and_monotonic_seq():
    bus = MessageBus()
    out_a = bus.stamp((BusMessage(topic="t1"), BusMessage(topic="t2")), source="SAT-01")
    out_b = bus.stamp((BusMessage(topic="t3"),), source="SAT-02")
    assert [m.source for m in out_a] == ["SAT-01", "SAT-01"]
    assert [m.seq for m in out_a] == [0, 1]
    assert out_b[0].source == "SAT-02"
    assert out_b[0].seq == 2  # 跨调用单调递增 → 确定性


def test_filter_for_keeps_only_subscribed_topics():
    msgs = (BusMessage(topic="a"), BusMessage(topic="b"), BusMessage(topic="a"))
    sel = MessageBus.filter_for(msgs, {"a"})
    assert len(sel) == 2
    assert all(m.topic == "a" for m in sel)
    assert MessageBus.filter_for(msgs, set()) == ()


def test_roundtrip_dict():
    m = BusMessage(topic="camera.photo_request", source="SAT-01",
                   data={"target": "SAT-02"}, seq=7)
    again = BusMessage.from_dict(m.to_dict())
    assert again == m
