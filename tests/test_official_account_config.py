"""Independent exact extraction proof; public app settings, never account login."""
import copy
import hashlib
import json

import pytest
from idoly_local import official_account_config as module

REPORT_SHA = "edc00afdbd45edde4d8fc6091a9016c03d92d4255df646b6f2273050fbe10a59"


def test_bundled_config_reconstructs_the_exact_verified_original_extraction_report():
    report = {"schema":1,"scope":"public-original-jp-client-configuration",
              "platforms":module.PUBLIC_CONFIG,"provenance":module.SOURCE_PROVENANCE,
              "official_authentication_attempted":False,"private_account_data_read":False}
    raw = (json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True)+"\n").encode()
    assert hashlib.sha256(raw).hexdigest() == REPORT_SHA
    for platform in ("ios","android"):
        value = module.load_public_config(platform)
        assert value["project_id"] == "solis-firebase"
        assert value["bundle_id"] == "game.qualiarts.idolypride"
        assert value["app_version"] == "6.1.1"
        assert module.SOURCE_PROVENANCE[platform]["identity_scope_verified"]
        assert module.SOURCE_PROVENANCE[platform]["app_executed"] is False
    ios = module.load_public_config("ios");android = module.load_public_config("android")
    assert ios["google_app_id"] != android["google_app_id"]
    assert "certificate_sha1" not in ios and len(android["certificate_sha1"]) == 40


def test_public_config_copies_cannot_change_later_sessions():
    first = module.load_public_config("ios")
    first["bundle_id"] = "unrelated"
    assert module.load_public_config("ios")["bundle_id"] == "game.qualiarts.idolypride"


@pytest.mark.parametrize("platform", ["ko", "", None, True, [], "iOS"])
def test_unknown_platform_fails_closed(platform):
    with pytest.raises(ValueError, match="^official_config_unavailable$"):
        module.load_public_config(platform)


@pytest.mark.parametrize("field,value", [("project_id","unrelated"),("bundle_id","unrelated"),
    ("google_app_id","1:543065248020:android:05fdc14eecbd124aab3201"),
    ("password","SYNTHETIC_PRIVATE_PASSWORD"),("api_key","malformed")])
def test_cross_scope_or_non_public_fields_never_become_runtime_configuration(monkeypatch,field,value):
    replacement = copy.deepcopy(module.PUBLIC_CONFIG)
    replacement["ios"][field] = value
    monkeypatch.setattr(module,"PUBLIC_CONFIG",replacement)
    with pytest.raises(ValueError) as error:
        module.load_public_config("ios")
    assert str(error.value) == "official_config_unavailable"
    assert value not in str(error.value)


def test_source_proof_change_fails_closed(monkeypatch):
    proof = copy.deepcopy(module.SOURCE_PROVENANCE)
    proof["ios"]["source"]["sha256"] = "0"*64
    monkeypatch.setattr(module,"SOURCE_PROVENANCE",proof)
    with pytest.raises(ValueError,match="^official_config_unavailable$"):
        module.load_public_config("ios")
