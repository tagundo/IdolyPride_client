"""Fresh-emulator startup completes only an observed, enabled app UI choice."""
import xml.etree.ElementTree as ET
import pytest

from test_tutorial_continuation_qa import qa


class ObservedUI:
    def __init__(self, xml):
        self.xml = xml
        self.observations = []
        self.touches = []
    def capture(self, stage):
        self.observations.append(stage)
        return ET.fromstring(self.xml)
    def tap(self, label, stage):
        self.touches.append((label,stage))


def test_fresh_storage_dialog_uses_existing_private_button():
    device = ObservedUI('<hierarchy><node text="권한 설정 열기" enabled="true" />'
                        '<node text="앱 전용으로 시작" enabled="true" /></hierarchy>')
    assert qa.complete_initial_storage_choice(device) is True
    assert device.observations == ["01-storage-choice"]
    assert device.touches == [("앱 전용으로 시작","01-storage-private-start")]


def test_absent_storage_dialog_leaves_startup_unchanged():
    device = ObservedUI('<hierarchy><node text="서버를 준비하고 있습니다…" enabled="true" /></hierarchy>')
    assert qa.complete_initial_storage_choice(device) is False
    assert device.touches == []


@pytest.mark.parametrize("enabled",["false","1",None])
def test_disabled_or_untyped_private_action_is_never_touched(enabled):
    attribute = '' if enabled is None else ' enabled="'+enabled+'"'
    device = ObservedUI('<hierarchy><node text="앱 전용으로 시작"'+attribute+' /></hierarchy>')
    assert qa.complete_initial_storage_choice(device) is False
    assert device.touches == []


def test_unparseable_observation_never_causes_input():
    device = ObservedUI('<hierarchy>')
    with pytest.raises(ET.ParseError):qa.complete_initial_storage_choice(device)
    assert device.touches == []
