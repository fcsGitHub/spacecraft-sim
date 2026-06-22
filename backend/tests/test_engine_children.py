from simcore.params import EntityInfo


def test_entityinfo_parent_default_empty():
    assert EntityInfo().parent == ""


def test_entityinfo_parent_set():
    assert EntityInfo(entity_id="C", parent="M").parent == "M"
