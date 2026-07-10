from medexa.api.body_region_labels import body_region_display


def test_body_region_display_maps_known_codes():
    assert body_region_display("shoulder_right") == "Right Shoulder"
    assert body_region_display("spine_lumbar") == "Lumbar Spine"


def test_body_region_display_handles_unknown():
    assert body_region_display("custom_region") == "Custom Region"
    assert body_region_display(None) is None
