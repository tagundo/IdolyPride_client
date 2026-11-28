"""Public NPC metadata audit boundaries; no Unity, network, game or mesh execution."""
from importlib.util import module_from_spec, spec_from_file_location
import hashlib
import json
from pathlib import Path
import stat
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

SPEC = spec_from_file_location("npc_audit", Path(__file__).resolve().parents[1] / "tools/audit_npc_models.py")
audit = module_from_spec(SPEC)
SPEC.loader.exec_module(audit)
NAME = audit.SELECTED_NAMES[0]


class Guard:
    def __init__(self):
        self.calls = 0

    def check(self):
        self.calls += 1


def test_original_toolkit_header_vector_and_tail_roundtrip():
    # Independent public 6.1.1 image-vector also checks the generalized mask.
    prefix = bytes.fromhex("9d47a54fbf76ad73d230d53ffb11ab1d")
    assert audit.crypt_header(prefix, "img_story_top_main-new").startswith(b"UnityFS\0")
    source = bytes(range(256)) + b"body-must-not-change"
    encoded = audit.crypt_header(source, NAME)
    assert encoded[256:] == source[256:] and encoded[:256] != source[:256]
    assert audit.crypt_header(encoded, NAME) == source


@pytest.mark.parametrize("name", ["../private", "mdl_a\nsecret", "mdl_"+"a"*161,
                                  "https://private.invalid", "mdl_한글", None, "mdl_"])
def test_untrusted_logical_names_are_rejected(name):
    with pytest.raises(audit.AuditError, match="logical_name"):
        audit.mask(name)


def good_bundle():
    raw = b"UnityFS\0bounded synthetic bundle"
    return raw, {"name": NAME, "size": len(raw),
                 "md5": hashlib.md5(raw).hexdigest(), "sha256": hashlib.sha256(raw).hexdigest()}


@pytest.mark.parametrize("field,value", [("size", 1), ("md5", "0"*32),
                                       ("sha256", "0"*64), ("name", "mdl_not_selected_body")])
def test_bundle_record_identity_and_both_digests_are_required(field, value):
    raw, fields = good_bundle()
    fields[field] = value
    with pytest.raises(audit.AuditError):
        audit.verify_bundle(raw, **fields)


def test_verified_plain_and_masked_unity_headers_are_accepted():
    raw, fields = good_bundle()
    assert audit.verify_bundle(raw, **fields) == raw
    encoded = audit.crypt_header(raw, NAME)
    fields.update(md5=hashlib.md5(encoded).hexdigest(), sha256=hashlib.sha256(encoded).hexdigest())
    assert audit.verify_bundle(encoded, **fields) == raw


def records(size=1):
    return [SimpleNamespace(name=name, kind="assetbundle", size=size) for name in audit.SELECTED_NAMES]


def test_exact_fixed_model_selection_rejects_missing_duplicates_and_resources():
    selected = records()
    assert [row.name for row in audit.select_records(selected)] == list(audit.SELECTED_NAMES)
    for altered in (selected[:-1], selected+[selected[0]]):
        with pytest.raises(audit.AuditError):
            audit.select_records(altered)
    selected[0].kind = "resources"
    with pytest.raises(audit.AuditError, match="duplicate_or_kind"):
        audit.select_records(selected)


def test_download_size_and_total_lifetime_allowance_are_bounded():
    selected = records(22 * audit.MIB)
    with pytest.raises(audit.AuditError, match="total_bound"):
        audit.select_records(selected)
    selected = records()
    selected[0].size = audit.MAX_OBJECT_BYTES + 1
    with pytest.raises(audit.AuditError, match="object_size_bound"):
        audit.select_records(selected)


def payload(tmp_path, monkeypatch, *, duplicate=False, symlink=False, missing=False):
    path = tmp_path / "public.zip"
    with ZipFile(path, "w") as archive:
        if symlink:
            entry = ZipInfo("data/public-octo/settings.json")
            entry.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(entry, b"target")
        else:
            archive.writestr("data/public-octo/settings.json", b"{}")
        if not missing:
            archive.writestr("data/public-octo/manifest.pb", b"public-manifest")
        archive.writestr("data/private/profile.db", b"must-not-be-extracted")
        if duplicate:
            with pytest.warns(UserWarning):
                archive.writestr("data/public-octo/settings.json", b"{}")
    monkeypatch.setattr(audit, "SERVER_BYTES", path.stat().st_size)
    monkeypatch.setattr(audit, "SERVER_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


def test_only_two_exact_pinned_public_members_are_extracted(tmp_path, monkeypatch):
    path = payload(tmp_path, monkeypatch)
    destination, guard = tmp_path / "selected", Guard()
    audit.extract_public_archive(path, destination, guard)
    assert {p.name: p.read_bytes() for p in destination.iterdir()} == {
        "settings.json": b"{}", "manifest.pb": b"public-manifest"}
    assert guard.calls == 2


@pytest.mark.parametrize("mutation,error", [("duplicate", "duplicate"), ("symlink", "bound"),
                                           ("missing", "incomplete")])
def test_public_archive_ambiguity_and_link_members_fail_closed(tmp_path, monkeypatch, mutation, error):
    path = payload(tmp_path, monkeypatch, **{mutation: True})
    with pytest.raises(audit.AuditError, match=error):
        audit.extract_public_archive(path, tmp_path / "selected", Guard())


def test_full_payload_digest_is_checked_before_zip_parsing_or_extraction(tmp_path, monkeypatch):
    path = tmp_path / "not-a-zip"
    path.write_bytes(b"untrusted bytes")
    monkeypatch.setattr(audit, "SERVER_BYTES", path.stat().st_size)
    monkeypatch.setattr(audit, "SERVER_SHA256", "0"*64)
    destination = tmp_path / "selected"
    with pytest.raises(audit.AuditError, match="pin_differs"):
        audit.extract_public_archive(path, destination, Guard())
    assert not destination.exists()


class Reader:
    def __init__(self, class_id, path_id, tree=None, error=None):
        self.class_id, self.path_id = class_id, path_id
        self.byte_size, self.assets_file = 100, SimpleNamespace(name="public-assets")
        self.tree, self.error, self.reads = tree or {}, error, 0

    def read_typetree(self):
        self.reads += 1
        if self.error:
            raise self.error
        return self.tree


def ptr(path_id, file_id=0):
    return {"m_FileID": file_id, "m_PathID": path_id}


def metadata():
    return [
        Reader(1, 1, {"m_Name": "Hips"}),
        Reader(4, 2, {"m_GameObject": ptr(1)}),
        Reader(1, 3, {"m_Name": "FullBodyIK"}),
        Reader(90, 4, {"m_Name": "Humanoid", "m_Avatar": {"m_Human": {"m_BoneIndex": [0]}}}),
        Reader(95, 5, {"m_GameObject": ptr(3), "m_Avatar": ptr(4)}),
        Reader(137, 6, {"m_GameObject": ptr(3), "m_Bones": [ptr(2)], "m_RootBone": ptr(2),
                        "m_BlendShapeWeights": [0.0, 0.0]}),
        Reader(115, 7, {"m_Name": "FacialDriver", "m_ClassName": "FacialDriver", "m_Namespace": "Solis"}),
        Reader(114, 8, {"m_GameObject": ptr(3), "m_Script": ptr(7)}),
    ]


def test_skin_avatar_and_facial_metadata_are_observed_without_runtime_claims():
    result = audit.summary(metadata(), name=NAME)
    assert result["resolved_skin_bone_names"] == ["Hips"]
    assert result["total_skin_bone_slots"] == 1
    assert result["human_avatar_structures"] == 1
    assert result["animators"][0]["avatar_resolved_in_bundle"] is True
    assert result["blend_shape_weight_slots"] == 2
    assert result["component_script_classes"] == ["Solis.FacialDriver"]
    assert result["rig_name_markers"] == ["FullBodyIK"]
    assert result["runtime_motion_tested"] is False and result["npc_enabled"] is False
    assert result["runtime_mv_compatibility"] == "NOT_TESTED"


def test_mesh_and_texture_objects_are_counted_but_never_read_or_exported():
    mesh, texture = Reader(43, 40, error=AssertionError()), Reader(28, 41, error=AssertionError())
    result = audit.summary([mesh, texture], name=NAME)
    assert mesh.reads == texture.reads == 0
    assert result["class_counts"] == {"28": 1, "43": 1}
    assert not result["game_object_names"] and not result["skinned_renderers"]


def test_external_dependencies_and_unreadable_trees_remain_explicitly_incomplete():
    rows = metadata()
    rows[4].tree["m_Avatar"] = ptr(1234, 1)
    rows[5].tree["m_Bones"] = [ptr(42, 2)]
    rows[7].tree["m_Script"] = ptr(99, 3)
    rows.append(Reader(114, 98, error=ValueError("https://secret.invalid/full/private/path")))
    result = audit.summary(rows, name=NAME)
    assert result["external_reference_count"] == 3
    assert result["unresolved_skin_bone_slots"] == 1
    assert result["unresolved_script_components"] == 1
    assert result["unreadable_type_tree_count"] == 1
    assert result["metadata_constraints"]
    assert "secret" not in json.dumps(result)
    assert result["runtime_mv_compatibility"] == "NOT_TESTED"


def test_names_type_tree_sizes_and_output_rows_are_bounded(monkeypatch):
    result = audit.summary([Reader(1, 1, {"m_Name": "x"*129}),
                            Reader(1, 2, {"m_Name": "/private/path"})], name=NAME)
    assert result["game_object_names"] == []
    reader = Reader(1, 3)
    reader.byte_size = audit.MAX_TREE_BYTES + 1
    result = audit.summary([reader], name=NAME)
    assert reader.reads == 0 and result["unreadable_type_tree_count"] == 1
    monkeypatch.setattr(audit, "MAX_NAMES", 2)
    with pytest.raises(audit.AuditError, match="name_count_bound"):
        audit.summary([Reader(1, n, {"m_Name": "node"+str(n)}) for n in range(3)], name=NAME)


def test_reader_iterable_is_stopped_at_the_bound_before_it_is_fully_materialized(monkeypatch):
    monkeypatch.setattr(audit, "MAX_READERS", 2)
    consumed = []
    def generate():
        for index in range(100):
            consumed.append(index)
            yield Reader(1, index)
    with pytest.raises(audit.AuditError, match="object_count_bound"):
        audit.summary(generate(), name=NAME)
    assert consumed == [0, 1, 2]


def test_unreadable_rows_have_a_bounded_excerpt_without_error_messages(monkeypatch):
    monkeypatch.setattr(audit, "MAX_UNREADABLE", 2)
    result = audit.summary([Reader(114, index, error=ValueError("private")) for index in range(5)], name=NAME)
    assert len(result["unreadable_type_trees"]) == 2
    assert result["unreadable_type_tree_count"] == 5
    assert "private" not in json.dumps(result)


def test_even_identical_bone_names_never_establish_runtime_compatibility():
    rows = [{"name": name, "resolved_skin_bone_names": ["Hips"]} for name in audit.SELECTED_NAMES]
    compared = audit.comparisons(rows)
    assert all(row["complete_bone_name_match"] is True for row in compared.values())
    assert all(row["runtime_mv_compatibility"] == "NOT_TESTED" and row["npc_enabled"] is False
               for row in compared.values())


def test_local_cli_identity_is_rejected_before_paths_or_project_imports(monkeypatch):
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    with pytest.raises(audit.AuditError, match="remote_actions_required"):
        audit.owned_main(SimpleNamespace(source_commit="a"*40))


def test_report_size_limit_prevents_partial_output(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "MAX_OUTPUT", 32)
    path = tmp_path / "report.json"
    with pytest.raises(audit.AuditError, match="size_bound"):
        audit.write_json(path, {"oversized": "x"*100})
    assert not path.exists()
