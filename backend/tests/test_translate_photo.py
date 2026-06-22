from simcore.scenario import EventDef
from simcore.translate import command_from_event


def test_photo_event_maps_to_camera_take_photo():
    cmd = command_from_event(EventDef(t=120, ev_type="拍照", target="SAT-01", action="拍照 TGT-01"))
    assert cmd is not None
    assert cmd.channel == "ctr"
    assert cmd.name == "take_photo"
    assert cmd.target_model == "camera"
    assert cmd.params["target"] == "TGT-01"
    assert cmd.entity_id == "SAT-01"


def test_photo_event_without_target_token_is_none():
    assert command_from_event(EventDef(t=120, ev_type="拍照", target="SAT-01", action="拍照")) is None
