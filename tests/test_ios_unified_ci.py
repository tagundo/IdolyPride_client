import importlib.util
from pathlib import Path

import pytest

path = Path(__file__).resolve().parents[1] / "ios-unified/ci_build.py"
spec = importlib.util.spec_from_file_location("unified_ci", path)
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def runtime(version, available=True, kind="iOS"):
    return {"identifier": "com.apple.CoreSimulator.SimRuntime." + kind + "-" + version.replace(".", "-"),
            "version": version, "isAvailable": available}


def test_active_xcode_18_sdk_avoids_newer_installed_26_runtime():
    catalog = {"runtimes": [runtime("26.2"), runtime("18.5"), runtime("18.4")]}
    assert ci.compatible_runtime("18.5", catalog).endswith("iOS-18-5")


def test_unavailable_or_other_platform_runtime_cannot_win():
    catalog = {"runtimes": [runtime("18.5", False), runtime("18.5", kind="tvOS"), runtime("18.4")]}
    assert ci.compatible_runtime("18.5.0", catalog).endswith("iOS-18-4")


def test_no_compatible_runtime_fails_before_simulator_creation():
    with pytest.raises(ValueError, match="compatible"):
        ci.compatible_runtime("18.5", {"runtimes": [runtime("26.2")]})


def test_server_data_upgrade_is_bound_to_fixed_base_proof_and_packaged_pin(tmp_path,monkeypatch):
    import hashlib
    import json
    from types import SimpleNamespace
    inputs=tmp_path/"inputs";work=tmp_path/"work";output=tmp_path/"output"
    for folder in (inputs,work,output):folder.mkdir()
    (inputs/"ServerData.zip").write_bytes(b"old-base")
    raw=b"latest-coherent-fixed-payload"
    base={"bytes":8,"sha256":"a"*64};pin={"bytes":len(raw),"sha256":hashlib.sha256(raw).hexdigest()}
    proof={"schema":1,"deterministic":"fixed-source-proof"}
    (tmp_path/"runtime_inputs.json").write_text(json.dumps({"inputs":{"server_data":base},"packaged_server_data":ci.PACKAGED_SERVER_DATA,"korean_master_refresh":ci.KOREAN_MASTER_REFRESH}))
    calls=[]
    def fetch(destination):
        assert destination==work/"latest-server-overlay.zip" and not destination.exists()
        destination.write_bytes(raw);calls.append("fetch-source");return pin
    def verify_overlay(path):assert path.read_bytes()==raw;calls.append("verify-overlay")
    def upgrade(source,destination,*,report_path,overlay_zip):
        assert overlay_zip==work/"latest-server-overlay.zip" and overlay_zip.read_bytes()==raw
        assert source==inputs/"ServerData.zip" and source.read_bytes()==b"old-base"
        assert not destination.exists();destination.write_bytes(overlay_zip.read_bytes());report_path.write_text(json.dumps(proof));calls.append("upgrade");return proof
    def verify_proof(value):assert value==proof;calls.append("verify-proof");return value
    def verify_payload(path):assert path.read_bytes()==raw;calls.append("verify-payload");return pin
    verifier=SimpleNamespace(base_pin=lambda:base,output_pin=lambda:pin,verify_upgrade_proof=verify_proof,verify_payload=verify_payload,
        verify_source_pointer=lambda:calls.append("verify-source-pointer"),fetch_overlay=fetch,verify_overlay=verify_overlay)
    korean_raw=b"final-korean-masters-with-original-latest-data"
    korean_proof={"schema":1,"base_payload":pin,"output":"frozen-korean-overlay"}
    def korean_refresh(source,destination):
        assert source==work/"upgraded-ServerData.zip" and source.read_bytes()==raw
        assert not destination.exists();destination.write_bytes(korean_raw);calls.append("korean-refresh");return korean_proof
    def korean_verify_proof(value):assert value==korean_proof;calls.append("korean-verify-proof")
    def korean_verify_payload(path):assert path.read_bytes()==korean_raw;calls.append("korean-verify-payload")
    monkeypatch.setattr(ci,"HERE",tmp_path)
    names=[]
    def tool(name):
        names.append(name)
        if name=="latest_server_data_pin":return verifier
        if name=="korean_server_data_pin":return SimpleNamespace(refresh_server_data=korean_refresh,
            verify_refresh_proof=korean_verify_proof,verify_payload=korean_verify_payload)
        assert name=="prepare_latest_server_data"
        return SimpleNamespace(upgrade_server_data=upgrade)
    monkeypatch.setattr(ci,"_tool_module",tool)
    upgraded,receipt=ci.prepare_server_data(inputs,work,output)
    assert upgraded==work/"korean-ServerData.zip" and receipt==output/"server-data-upgrade.json"
    assert calls==["verify-source-pointer","fetch-source","verify-overlay","upgrade","verify-proof","verify-payload",
                   "korean-refresh","korean-verify-proof","korean-verify-payload"]
    assert names==["latest_server_data_pin","prepare_latest_server_data","korean_server_data_pin"]
    assert json.loads(receipt.read_bytes())==proof
    assert json.loads((output/"server-data-korean-refresh.json").read_bytes())==korean_proof
    assert (inputs/"ServerData.zip").read_bytes()==b"old-base"


def test_missing_static_server_data_pin_stops_before_upgrader_or_any_native_build(tmp_path,monkeypatch):
    import json
    from types import SimpleNamespace
    (tmp_path/"runtime_inputs.json").write_text(json.dumps({"inputs":{"server_data":{"bytes":1,"sha256":"a"*64}},"packaged_server_data":ci.PACKAGED_SERVER_DATA,"korean_master_refresh":ci.KOREAN_MASTER_REFRESH}))
    names=[]
    def tools(name):
        names.append(name)
        def missing():raise ValueError("latest_server_data_pin_missing")
        return SimpleNamespace(base_pin=lambda:{"bytes":1,"sha256":"a"*64},output_pin=missing)
    monkeypatch.setattr(ci,"HERE",tmp_path);monkeypatch.setattr(ci,"_tool_module",tools)
    with pytest.raises(ValueError,match="latest_server_data_pin_missing"):
        ci.prepare_server_data(tmp_path,tmp_path,tmp_path)
    assert names==["latest_server_data_pin"]


@pytest.mark.parametrize("marker",[None,{"pin":"/private/other.json","policy":"latest-cohort-overlay-v1"},{"pin":"../data/latest-server-data-pin.json","policy":"accept-any-sha"},{"pin":"../data/love-server-data-pin.json","policy":"love-source-overlay-v1"}])
def test_server_data_upgrade_never_accepts_arbitrary_pin_paths_or_missing_marker(tmp_path,monkeypatch,marker):
    import json
    manifest={"inputs":{"server_data":{"bytes":1,"sha256":"a"*64}}}
    if marker is not None:manifest["packaged_server_data"]=marker
    (tmp_path/"runtime_inputs.json").write_text(json.dumps(manifest));monkeypatch.setattr(ci,"HERE",tmp_path)
    monkeypatch.setattr(ci,"_tool_module",lambda name:pytest.fail("No module should load for an unapproved marker"))
    with pytest.raises(ValueError,match="Pinned upgraded server data"):
        ci.prepare_server_data(tmp_path,tmp_path,tmp_path)


@pytest.mark.parametrize("changed", [{"bytes":1},{"sha256":"f"*64}])
def test_wrong_fetched_latest_source_identity_stops_before_upgrader(tmp_path,monkeypatch,changed):
    import json
    from types import SimpleNamespace
    base={"bytes":8,"sha256":"a"*64};pin={"bytes":12,"sha256":"b"*64}
    (tmp_path/"runtime_inputs.json").write_text(json.dumps({"inputs":{"server_data":base},"packaged_server_data":ci.PACKAGED_SERVER_DATA,"korean_master_refresh":ci.KOREAN_MASTER_REFRESH}))
    verifier=SimpleNamespace(base_pin=lambda:base,output_pin=lambda:pin,verify_source_pointer=lambda:None,
        fetch_overlay=lambda destination:{**pin,**changed})
    monkeypatch.setattr(ci,"HERE",tmp_path)
    monkeypatch.setattr(ci,"_tool_module",lambda name:verifier if name=="latest_server_data_pin" else SimpleNamespace())
    with pytest.raises(ValueError,match="Fetched server data source pin differs"):
        ci.prepare_server_data(tmp_path,tmp_path,tmp_path)
