"""XML regressions for the one known disposable AVD launcher environment fault."""
import importlib.util
import json
from pathlib import Path
import xml.etree.ElementTree as ET
import pytest

SPEC = importlib.util.spec_from_file_location("qa_launcher_guard", Path(__file__).with_name("qa_launcher_guard.py"))
guard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)
EVIDENCE = {"kind": "android_emulator", "ro.kernel.qemu": "1"}
SERVER = '<hierarchy><node package="game.qualiarts.idolypride.localserver" text="서버 시작" enabled="true" bounds="[20,100][900,200]"/></hierarchy>'


def dialog(title=guard.TITLE, *, package="android", enabled="true", clickable="true", close_bounds="[72,1051][1008,1183]"):
    return ('<hierarchy><node package="'+package+'" resource-id="android:id/alertTitle" text="'+title+'"/>'
            '<node package="android" resource-id="android:id/aerr_close" text="Close app" enabled="'+enabled+'" clickable="'+clickable+'" bounds="'+close_bounds+'"/>'
            '<node package="android" resource-id="android:id/aerr_wait" text="Wait" enabled="true" clickable="true" bounds="[72,1183][1008,1315]"/></hierarchy>')


class Guest:
    def __init__(self, path, trees, *, home=None, system_path=None):
        self.artifacts, self.trees, self.actions, self.captures = path, list(trees), [], []
        self.home = home or guard.LAUNCHER+'/.NexusLauncherActivity'
        self.system_path = system_path or 'package:/product/priv-app/NexusLauncherRelease/NexusLauncherRelease.apk'
    def capture(self, stage):
        self.captures.append(stage)
        return ET.fromstring(self.trees.pop(0))
    def adb(self, *args):
        self.actions.append(args)
        if args[:4] == ('shell', 'cmd', 'package', 'resolve-activity'): return self.home
        if args[:3] == ('shell', 'pm', 'path'): return self.system_path
        return ''


def inputs(guest):
    return [value for value in guest.actions if value[:3] == ('shell', 'input', 'tap')]


def test_observed_system_launcher_close_is_singular_and_actual_server_is_reobserved(tmp_path):
    guest = Guest(tmp_path, [dialog(), dialog(), SERVER])
    guard.recover_initial_launcher(guest, EVIDENCE)
    assert inputs(guest) == [('shell','input','tap','540','1117')]
    assert ('shell','am','start','-W','-n',guard.ACTIVITY) in guest.actions
    assert guest.captures == ['00-launcher-before','00-launcher-confirm','00-launcher-after']
    record = json.loads((tmp_path/'00-launcher-incident.json').read_text())
    assert record['incident_count'] == 1 and record['performed'] is True and record['resolved'] is True
    assert record['checkpoint'] == 'before_initial_server_start' and record['component'] == guard.LAUNCHER
    assert record['before_xml'] == '00-launcher-before.xml' and record['after_xml'] == '00-launcher-after.xml'


def test_clear_server_ui_never_sends_launcher_inputs_or_queries(tmp_path):
    guest = Guest(tmp_path, [SERVER])
    guard.recover_initial_launcher(guest, EVIDENCE)
    assert guest.actions == [] and not (tmp_path/'00-launcher-incident.json').exists()


@pytest.mark.parametrize('xml', [dialog("IdolyPride Local Server isn't responding"), dialog("Other app isn't responding"),
    dialog(package='arbitrary.app'), dialog(enabled='false'), dialog(clickable='false'), dialog(close_bounds='[0,0][0,0]'),
    '<hierarchy><node package="android" resource-id="android:id/alertTitle" text="System update"/></hierarchy>'])
def test_own_server_unknown_dialog_and_unusable_button_cannot_be_dismissed(tmp_path, xml):
    guest = Guest(tmp_path, [xml])
    with pytest.raises(RuntimeError, match='unapproved'):
        guard.recover_initial_launcher(guest, EVIDENCE)
    assert guest.actions == [] and inputs(guest) == []


@pytest.mark.parametrize('home,path', [('arbitrary.app/.Activity',None),
    (guard.LAUNCHER+'/.NexusLauncherActivity','package:/data/app/other/base.apk')])
def test_same_label_is_insufficient_without_known_system_home_target(tmp_path, home, path):
    guest = Guest(tmp_path, [dialog()], home=home, system_path=path)
    with pytest.raises(RuntimeError, match='verified'):
        guard.recover_initial_launcher(guest, EVIDENCE)
    assert inputs(guest) == []
    assert json.loads((tmp_path/'00-launcher-incident.json').read_text())['performed'] is False


@pytest.mark.parametrize('changed', [SERVER, dialog("IdolyPride Local Server isn't responding"),
                                     dialog(close_bounds='[80,1051][1008,1183]')])
def test_fresh_changed_or_disappeared_dialog_never_receives_a_stale_tap(tmp_path, changed):
    guest = Guest(tmp_path, [dialog(), changed])
    with pytest.raises(RuntimeError): guard.recover_initial_launcher(guest, EVIDENCE)
    assert inputs(guest) == [] and len(guest.captures) == 2


@pytest.mark.parametrize('after', [dialog(), dialog("IdolyPride Local Server isn't responding"), '<hierarchy/>'])
def test_unresolved_anr_or_missing_real_server_ui_fails_after_only_one_input(tmp_path, after):
    guest = Guest(tmp_path, [dialog(), dialog(), after])
    with pytest.raises(RuntimeError): guard.recover_initial_launcher(guest, EVIDENCE)
    assert len(inputs(guest)) == 1
    record = json.loads((tmp_path/'00-launcher-incident.json').read_text())
    assert record['performed'] is True and record['resolved'] is False


def test_repeated_launcher_incident_cannot_send_a_second_close_input(tmp_path):
    guest = Guest(tmp_path, [dialog(), dialog(), SERVER, dialog()])
    guard.recover_initial_launcher(guest, EVIDENCE)
    with pytest.raises(RuntimeError, match='one attempt'):
        guard.recover_initial_launcher(guest, EVIDENCE)
    assert len(inputs(guest)) == 1
    assert json.loads((tmp_path/'00-launcher-incident.json').read_text())['incident_count'] == 2


@pytest.mark.parametrize('evidence', [{}, {'kind':'physical_device','ro.kernel.qemu':'0'},
                                      {'kind':'android_emulator','ro.kernel.qemu':'0'}])
def test_unverified_or_physical_target_is_rejected_before_any_surface_access(tmp_path, evidence):
    guest = Guest(tmp_path, [dialog()])
    with pytest.raises(RuntimeError, match='verified disposable'):
        guard.recover_initial_launcher(guest, evidence)
    assert guest.actions == [] and guest.captures == []
