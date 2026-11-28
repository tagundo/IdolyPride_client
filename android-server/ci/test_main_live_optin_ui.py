"""Main-live opt-in follows observed viewports and requires checked readback."""
import xml.etree.ElementTree as ET
import pytest

from test_tutorial_continuation_qa import qa

LABEL = "첫 메인 라이브 실험 기능 사용"
VIEW = '<hierarchy><node class="android.widget.ScrollView" scrollable="true" bounds="[50,100][1000,1500]">' \
       '<node class="android.widget.ScrollView" scrollable="true" bounds="[200,800][800,1450]" />' \
       '<node class="android.widget.Spinner" scrollable="false" bounds="[100,200][950,650]" /></node></hierarchy>'


def checkbox(checked="false",enabled="true"):
    return '<hierarchy><node text="'+LABEL+'" class="android.widget.CheckBox" checkable="true" checked="'+checked+'" enabled="'+enabled+'" bounds="[70,300][950,390]" /></hierarchy>'


class FakeUI:
    def __init__(self,frames):
        self.frames=list(frames);self.index=0;self.captures=[];self.taps=[];self.swipes=[]
    def capture(self,stage):
        self.captures.append(stage)
        frame=self.frames[min(self.index,len(self.frames)-1)];self.index+=1
        return ET.fromstring(frame)
    def tap(self,label,stage):self.taps.append((label,stage))
    def adb(self,*arguments):
        assert arguments[:3]==("shell","input","swipe")
        self.swipes.append(arguments)


def test_swipe_uses_largest_observed_main_view_and_avoids_nested_start():
    x1,y1,x2,y2=qa._main_options_swipe(ET.fromstring(VIEW))
    assert 50<x1==x2<1000 and 100<y1<y2<1500
    assert not (200<=x1<800 and 800<=y1<1450)
    assert not (100<=x1<950 and 200<=y1<650)


def test_scroll_then_actual_tap_requires_checked_readback(monkeypatch):
    monkeypatch.setattr(qa.time,"sleep",lambda _seconds:None)
    device=FakeUI([VIEW,checkbox(),checkbox("true")])
    assert qa.enable_main_live_through_ui(device,max_scrolls=2) is True
    assert len(device.swipes)==1
    assert device.taps==[(LABEL,"48-main-live-opt-in")]
    assert device.captures[-1]=="48-main-live-checked-0"


def test_absent_checkbox_has_bounded_main_view_scrolls(monkeypatch):
    monkeypatch.setattr(qa.time,"sleep",lambda _seconds:None)
    device=FakeUI([VIEW])
    with pytest.raises(RuntimeError,match="bounded observations"):
        qa.enable_main_live_through_ui(device,max_scrolls=2)
    assert len(device.swipes)==2 and len(device.captures)==3 and device.taps==[]


def test_disabled_checkbox_is_never_touched_and_fails_bounded(monkeypatch):
    monkeypatch.setattr(qa.time,"sleep",lambda _seconds:None)
    device=FakeUI([checkbox(enabled="false")])
    with pytest.raises(RuntimeError,match="bounded observations"):
        qa.enable_main_live_through_ui(device,max_scrolls=2)
    assert len(device.captures)==3 and device.taps==[] and device.swipes==[]


def test_failed_checked_readback_cannot_satisfy_optin(monkeypatch):
    monkeypatch.setattr(qa.time,"sleep",lambda _seconds:None)
    device=FakeUI([checkbox()])
    with pytest.raises(RuntimeError,match="did not become checked"):
        qa.enable_main_live_through_ui(device,max_scrolls=0)
    assert len(device.taps)==1 and len(device.captures)==6 and device.swipes==[]


def test_already_checked_checkbox_is_not_toggled_off():
    device=FakeUI([checkbox("true")])
    with pytest.raises(RuntimeError,match="initially unchecked"):
        qa.enable_main_live_through_ui(device,max_scrolls=0)
    assert device.taps==[]


def test_no_observed_main_view_means_no_blind_swipe():
    device=FakeUI(['<hierarchy />'])
    with pytest.raises(RuntimeError,match="not observable"):
        qa.enable_main_live_through_ui(device,max_scrolls=1)
    assert device.swipes==[] and device.taps==[]
