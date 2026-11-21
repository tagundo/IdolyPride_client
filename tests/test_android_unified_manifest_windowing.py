from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from tools import package_android_unified as unified


A = unified.ANDROID


def compiled_manifest():
    root = ET.Element("manifest")
    app = ET.SubElement(root, "application", {A + "resizeableActivity": "true"})
    ET.SubElement(app, "activity", {A + "name": unified.GAME_ACTIVITY,
        A + "resizeableActivity": "true", A + "screenOrientation": "fullUser",
        A + "configChanges": "|".join((*unified.WINDOW_CONFIG_CHANGES, "uiMode", "fontScale"))})
    ET.SubElement(app, "activity", {A + "name": unified.MENU_ACTIVITY, A + "resizeableActivity": "true"})
    return root


def test_compiled_policy_keeps_additional_unity_configuration_handlers():
    root = compiled_manifest()
    result = unified.windowing_policy(ET.tostring(root))
    assert result["application_resizable"] and result["game_resizable"] and result["menu_resizable"]
    assert {"uiMode", "fontScale", *unified.WINDOW_CONFIG_CHANGES} == set(result["game_config_changes"])
    assert result["game_orientation"] == "fullUser"


@pytest.mark.parametrize("scope", ["application", "application/activity", "application/activity[2]"])
def test_readback_rejects_resizing_lock_at_either_level(scope):
    root = compiled_manifest()
    root.find(scope).set(A + "resizeableActivity", "false")
    with pytest.raises(ValueError, match="resizing"):
        unified.windowing_policy(ET.tostring(root))


@pytest.mark.parametrize("missing", unified.WINDOW_CONFIG_CHANGES)
def test_readback_rejects_a_lost_fold_configuration_flag(missing):
    root = compiled_manifest()
    game = root.find("application/activity")
    game.set(A + "configChanges", "|".join(v for v in unified.WINDOW_CONFIG_CHANGES if v != missing))
    with pytest.raises(ValueError, match="Fold configuration"):
        unified.windowing_policy(ET.tostring(root))


@pytest.mark.parametrize("scope", ["application", "application/activity"])
@pytest.mark.parametrize("restriction", ["minAspectRatio", "maxAspectRatio", "android.max_aspect"])
def test_readback_rejects_aspect_compatibility_caps(scope, restriction):
    root = compiled_manifest()
    node = root.find(scope)
    if restriction == "android.max_aspect":
        ET.SubElement(node, "meta-data", {A + "name": restriction, A + "value": "2.33334"})
    else:
        node.set(A + restriction, "2.33334")
    with pytest.raises(ValueError, match="aspect ratio"):
        unified.windowing_policy(ET.tostring(root))
