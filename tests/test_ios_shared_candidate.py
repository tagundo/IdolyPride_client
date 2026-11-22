"""Fresh native-candidate admission; no physical game-execution claim."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parents[1] / "ios-unified"
sys.path.insert(0, str(HERE))
import presentation_candidate as candidate

PHOTO_HOOKS = frozenset(("mp4_photography_initialize", "mp4_photography_player_initialize", "mp4_photography_end"))


def library_fixture(tmp_path, monkeypatch):
    root = tmp_path / "source"
    names = ["client-presentation/native/bridge.cpp", "client-presentation/native/shared_cache_core.hpp",
             "client-presentation/native/shared_cache_hooks.hpp", "client-presentation/ios/static_install.hpp",
             "client-presentation/ios/build_native.py"]
    sources = {}
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("current source: " + name)
        sources[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    library = tmp_path / "IdolyPresentation.dylib"
    library.write_bytes(b"fresh compiled bridge")
    plan = {"profile_header_sha256": "a" * 64}
    receipt = {"schema": 1, "target": "arm64-apple-ios13.0", "bytes": library.stat().st_size,
               "sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
               "profile_header_sha256": plan["profile_header_sha256"], "source_sha256": sources}
    library.with_suffix(".build.json").write_text(json.dumps(receipt))
    monkeypatch.setattr(candidate, "audit_macho", lambda *a, **k: {
        "slices": [{"install_name": "@rpath/IdolyPresentation.dylib"}]})
    return root, library, plan, receipt


def test_old_bridge_receipt_cannot_replace_current_common_cache_code(tmp_path, monkeypatch):
    root, library, plan, receipt = library_fixture(tmp_path, monkeypatch)
    assert candidate.validate_library(library, plan, source_root=root)["fresh_source_build"]
    (root / "client-presentation/native/shared_cache_core.hpp").write_text("changed after compilation")
    with pytest.raises(ValueError, match="sources changed"):
        candidate.validate_library(library, plan, source_root=root)


@pytest.mark.parametrize("size", [2 * 1024**2 + 1, 4 * 1024**2])
def test_large_generated_bridge_keeps_exact_source_hash_validation(tmp_path, monkeypatch, size):
    root, library, plan, receipt = library_fixture(tmp_path, monkeypatch)
    name = "client-presentation/native/bridge.cpp"
    path = root / name
    path.write_bytes(b"A" * size)
    receipt["source_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    library.with_suffix(".build.json").write_text(json.dumps(receipt))
    assert candidate.validate_library(library, plan, source_root=root)["fresh_source_build"]
    with path.open("r+b") as output:
        output.seek(size - 1)
        output.write(b"B")
    with pytest.raises(ValueError, match="sources changed"):
        candidate.validate_library(library, plan, source_root=root)


@pytest.mark.parametrize("name,size", [
    ("client-presentation/native/bridge.cpp", 4 * 1024**2 + 1),
    ("client-presentation/native/shared_cache_core.hpp", 2 * 1024**2 + 1),
    ("client-presentation/ios/bridge.cpp", 2 * 1024**2 + 1),
    ("client-presentation/native/other/bridge.cpp", 2 * 1024**2 + 1),
])
def test_generated_bridge_exception_does_not_widen_other_source_limits(tmp_path, monkeypatch, name, size):
    root, library, plan, receipt = library_fixture(tmp_path, monkeypatch)
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"A" * size)
    receipt["source_sha256"][name] = hashlib.sha256(path.read_bytes()).hexdigest()
    library.with_suffix(".build.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError, match="Input exceeds size bound"):
        candidate.validate_library(library, plan, source_root=root)


@pytest.mark.parametrize("mutation", [
    lambda receipt: receipt["source_sha256"].pop("client-presentation/native/shared_cache_hooks.hpp"),
    lambda receipt: receipt.update(profile_header_sha256="b" * 64),
    lambda receipt: receipt.update(sha256="0" * 64),
    lambda receipt: receipt["source_sha256"].update({"client-presentation/../../private": "0" * 64}),
])
def test_mismatched_or_incomplete_fresh_bridge_receipt_fails(tmp_path, monkeypatch, mutation):
    root, library, plan, receipt = library_fixture(tmp_path, monkeypatch)
    mutation(receipt)
    library.with_suffix(".build.json").write_text(json.dumps(receipt))
    with pytest.raises(ValueError):
        candidate.validate_library(library, plan, source_root=root)


def test_verifier_reproduces_every_unity_byte_before_accepting_candidate(tmp_path, monkeypatch):
    raw = bytearray(b"verified stock plus known executable patches" * 5000)
    unity = tmp_path / "UnityFramework"
    unity.write_bytes(raw)
    proof = {"stock_unity_sha256": "1" * 64, "output_unity_sha256": hashlib.sha256(raw).hexdigest(),
             "output_bytes": len(raw)}
    calls = []
    monkeypatch.setattr(candidate, "load_plan", lambda path: calls.append("plan") or {})
    monkeypatch.setattr(candidate, "validate_library", lambda *a: calls.append("library") or {"sha256": "2" * 64})
    monkeypatch.setattr(candidate, "build_unity", lambda *a: calls.append("reproduce") or (raw, proof))
    result = candidate.verify("stock.ipa", unity, "plan.json", "bridge.dylib")
    assert calls == ["plan", "library", "reproduce"]
    assert result["verification"] == "reproduced_stock_bootstrap_and_current_presentation"
    with unity.open("r+b") as output:
        output.seek(100000)
        output.write(b"unexpected code")
    with pytest.raises(ValueError, match="reproduced stock patch"):
        candidate.verify("stock.ipa", unity, "plan.json", "bridge.dylib")


def test_candidate_filename_contains_source_date_and_commit(monkeypatch):
    spec = importlib.util.spec_from_file_location("candidate_ci", HERE / "ci_build.py")
    ci = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ci)
    monkeypatch.setattr(ci.subprocess, "check_output", lambda *a, **k: "2026-11-20\n")
    assert ci.candidate_filename("b" * 40) == "IdolyPride-Unified-2026.11.20-prototype-bbbbbbbbbbbb-iOS.ipa"
    with pytest.raises(ValueError):
        ci.candidate_filename("branch")


def test_unity_publication_preserves_a_concurrently_created_destination(tmp_path,monkeypatch):
    output=tmp_path/'UnityFramework'
    raw=bytearray(b'reproduced image')
    monkeypatch.setattr(candidate,'load_plan',lambda path:{})
    monkeypatch.setattr(candidate,'build_unity',lambda *args:(raw,{
        'output_unity_sha256':hashlib.sha256(raw).hexdigest()}))
    def racing_publication(staged,destination):
        Path(destination).write_bytes(b'other valid owner')
        raise FileExistsError('destination was published')
    monkeypatch.setattr(candidate.os,'link',racing_publication)
    with pytest.raises(FileExistsError):candidate.compose('stock.ipa','plan.json',output)
    assert output.read_bytes()==b'other valid owner'
    assert not output.with_suffix('.json').exists()


def base_delta_fixture(tmp_path,monkeypatch,*,later_hooks=False):
    old=bytearray(b'old executable and existing hooks'.ljust(8192,b'\0'))
    entries={}
    for index,name in enumerate(candidate.BASE_PRESENTATION_HOOKS):
        at,gateway=4096+index*32,6144+index*32
        old[at:at+16]=bytes([index+1])*16
        old[gateway:gateway+28]=bytes([index+2])*28
        entries[name]={'rva':at,'gateway':gateway,'original16':(bytes([index+3])*16).hex(),
                       'patched_entry':old[at:at+4].hex(),'gateway_hex':old[gateway:gateway+28].hex()}
    additions=sorted(candidate.NEW_BASE_HOOKS)
    if later_hooks:
        additions+=['mp4_capture_native_publication','mp4_fixed_loop_condition','mp4_context_submit']
    for index,name in enumerate(additions):
        at,gateway=256+index*32,1024+index*32
        prefix=bytes([index+1])*16
        old[at:at+16]=prefix
        entries[name]={'rva':at,'gateway':gateway,'original16':prefix.hex(),
                       'patched_entry':(bytes([index+9])*4).hex(),
                       'gateway_hex':(bytes([index+19])*(32 if name=='mp4_fixed_loop_condition' else 28)).hex()}
    if later_hooks:
        entries['mp4_capture_native_publication'].update(relay_in=2048,relay_out=2052,
            relay_in_hex='01000014',relay_out_hex='02000014')
    # Existing branch/gateway data is outside every newly allowed span.
    old[1800:1816]=bytes.fromhex('40000014f44f01a9fd7b02a9fd830091')
    old[1900:1928]=bytes(range(1,29))
    expected=bytearray(old)
    expected[16]=77
    for name in additions:
        row=entries[name]
        expected[row['rva']:row['rva']+4]=bytes.fromhex(row['patched_entry'])
        code=bytes.fromhex(row['gateway_hex'])
        expected[row['gateway']:row['gateway']+len(code)]=code
        if 'relay_in' in row:
            for field in ('relay_in','relay_out'):
                expected[row[field]:row[field]+4]=bytes.fromhex(row[field+'_hex'])
    path=tmp_path/'UnityFramework';path.write_bytes(expected)
    monkeypatch.setattr(candidate,'MAX_HEADER',128)
    plan={'entries':entries,'hook_names':[*candidate.BASE_PRESENTATION_HOOKS,*additions]}
    monkeypatch.setattr(candidate,'load_plan',lambda path:plan)
    def header(raw,size):
        value=bytearray(raw);value[16]=77
        return bytes(value),{'unchanged_layout':True}
    monkeypatch.setattr(candidate,'patched_header',header)
    return old,expected,path,entries


def test_later_validated_managed_conditional_and_native_relay_additions_are_reproduced(tmp_path,monkeypatch):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch,later_hooks=True)
    proof=candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')
    assert proof['new_hook_count']==18
    assert proof['new_native_relay_hooks']==['mp4_capture_native_publication']
    assert {'mp4_capture_native_publication','mp4_fixed_loop_condition','mp4_context_submit'} <= set(proof['new_mp4_hooks'])
    assert proof['output_unity_sha256']==hashlib.sha256(expected).hexdigest()


@pytest.mark.parametrize('location',['entry','original_tail','gateway','conditional_last_word','relay_in','relay_out'])
def test_later_additions_require_exact_old_source_prefix_and_zero_slack(tmp_path,monkeypatch,location):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch,later_hooks=True)
    row=entries['mp4_capture_native_publication'];conditional=entries['mp4_fixed_loop_condition']
    at={'entry':row['rva'],'original_tail':row['rva']+15,'gateway':row['gateway'],
        'conditional_last_word':conditional['gateway']+31,'relay_in':row['relay_in'],'relay_out':row['relay_out']}[location]
    old[at]^=1
    with pytest.raises(ValueError,match='prefix or zero gateway'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')


@pytest.mark.parametrize('location',['entry','gateway','conditional_last_word','relay_in','relay_out','past_relay','baseline_entry','baseline_gateway','bootstrap'])
def test_later_plan_never_substitutes_for_exact_executable_bytes_or_broadens_old_sites(tmp_path,monkeypatch,location):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch,later_hooks=True)
    row=entries['mp4_capture_native_publication'];conditional=entries['mp4_fixed_loop_condition']
    baseline=entries[candidate.BASE_PRESENTATION_HOOKS[0]]
    at={'entry':row['rva'],'gateway':row['gateway'],'conditional_last_word':conditional['gateway']+31,
        'relay_in':row['relay_in'],'relay_out':row['relay_out'],'past_relay':row['relay_out']+4,
        'baseline_entry':baseline['rva'],'baseline_gateway':baseline['gateway'],'bootstrap':64}[location]
    expected[at]^=1;path.write_bytes(expected)
    with pytest.raises(ValueError,match='prior bootstrap, presentation or SDK byte'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')


def test_previous_base_delta_preserves_old_hooks_and_all_other_sdk_bytes(tmp_path,monkeypatch):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch)
    proof=candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')
    assert proof['previous_bootstrap_and_presentation_bytes_preserved'] is True
    assert proof['new_hook_count']==15
    assert PHOTO_HOOKS <= set(proof['new_mp4_hooks'])
    assert proof['new_mp4_hooks']==sorted(candidate.MP4_HOOKS)
    assert proof['new_shared_hooks']==sorted(candidate.SHARED_HOOKS)
    expected[2000]=1;path.write_bytes(expected)
    with pytest.raises(ValueError,match='prior bootstrap, presentation or SDK byte'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')


@pytest.mark.parametrize('name',sorted(candidate.MP4_HOOKS))
@pytest.mark.parametrize('offset', [0,8])
def test_mp4_delta_rejects_changed_source_prefix_or_nonzero_gateway(tmp_path,monkeypatch,name,offset):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch)
    row=entries[name]
    at=row['rva']+offset if offset else row['gateway']
    old[at]^=1
    with pytest.raises(ValueError,match='prefix or zero gateway'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')


@pytest.mark.parametrize('location',['old_entry','old_gateway','new_gateway_padding','unrelated_data'])
def test_mp4_delta_never_allows_old_patches_padding_or_other_data_changes(tmp_path,monkeypatch,location):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch)
    row=entries['mp4_presenter_update']
    at={'old_entry':1800,'old_gateway':1900,'new_gateway_padding':row['gateway']+28,'unrelated_data':2000}[location]
    expected[at]^=1;path.write_bytes(expected)
    with pytest.raises(ValueError,match='prior bootstrap, presentation or SDK byte'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')


@pytest.mark.parametrize('name',sorted(PHOTO_HOOKS))
def test_photography_route_requires_every_named_hook_in_the_candidate_plan(tmp_path,monkeypatch,name):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch)
    assert PHOTO_HOOKS <= candidate.MP4_HOOKS
    incomplete=dict(entries);incomplete.pop(name)
    monkeypatch.setattr(candidate,'load_plan',lambda path:{'entries':incomplete})
    with pytest.raises(ValueError,match='additional hook plan is incomplete'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')
    assert path.read_bytes()==expected


@pytest.mark.parametrize('name',sorted(PHOTO_HOOKS))
@pytest.mark.parametrize('part',['entry','gateway'])
def test_photography_hook_declaration_cannot_substitute_for_its_patched_executable_bytes(tmp_path,monkeypatch,name,part):
    old,expected,path,entries=base_delta_fixture(tmp_path,monkeypatch)
    row=entries[name]
    at,size=(row['rva'],4) if part=='entry' else (row['gateway'],len(bytes.fromhex(row['gateway_hex'])))
    expected[at:at+size]=old[at:at+size];path.write_bytes(expected)
    with pytest.raises(ValueError,match='prior bootstrap, presentation or SDK byte'):
        candidate.verify_base_delta(io.BytesIO(old),path,hashlib.sha256(old).hexdigest(),'plan.json')
