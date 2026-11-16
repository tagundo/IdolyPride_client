"""Private downloads retain raw proofs, actual dated filenames and byte identity."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import stat
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


stager = load("private_staging_tests", "tools/stage_private_candidate.py")
names = load("private_staging_names", "tools/release_identity.py")
SOURCE, RUN, VERSION = "a" * 40, 42, "2026.11.16.2"
RAW = {"android": "IdolyPride-Local-Server-Android.apk",
       "ios-unified": "IdolyPride-6.1.1-Unified-iOS.ipa"}
JOBS = ("portable", "performance", "android", "android-clients", "ios-unified")


class Guard:
    def check(self):
        pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(directory, row):
    path = directory / row["name"]
    assert stat.S_ISREG(path.lstat().st_mode)
    assert path.stat().st_size == row["bytes"] and digest(path) == row["sha256"]
    return path


def publisher():
    return SimpleNamespace(APK=RAW["android"], IPA=RAW["ios-unified"], JOBS=JOBS, verified_file=verify)


def inputs(tmp_path):
    rows = []
    for role, name in RAW.items():
        folder = tmp_path / "original" / role
        folder.mkdir(parents=True)
        path = folder / name
        path.write_bytes(b"PK-private-fixture-" + role.encode())
        rows.append({"path": str(path), "name": name, "bytes": path.stat().st_size, "sha256": digest(path)})
    return rows


def test_actual_download_basenames_contain_date_and_raw_files_remain(tmp_path):
    rows = inputs(tmp_path)
    before = {row["path"]: Path(row["path"]).read_bytes() for row in rows}
    result = stager.stage_copies(rows, tmp_path / "private", VERSION, publisher(), names, Guard())
    assert {row["name"] for row in result} == {
        "IdolyPride-2026.11.16.2-Server-Android.apk",
        "IdolyPride-2026.11.16.2-Unified-iOS.ipa"}
    assert {row["artifact_directory"] for row in result} == set(RAW)
    for row in result:
        target = tmp_path / "private" / row["artifact_directory"] / row["name"]
        assert digest(target) == row["sha256"]
        assert target.read_bytes() == next(raw for path, raw in before.items() if Path(path).name == row["source_name"])
    assert all(Path(path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("version", ["0.3.36", "2026.11.16.02", "2026.02.29.1", "2026.11.16.2/other"])
def test_invalid_candidate_dates_cannot_create_output(tmp_path, version):
    with pytest.raises(ValueError, match="release_version_invalid"):
        stager.stage_copies(inputs(tmp_path), tmp_path / "private", version, publisher(), names, Guard())
    assert not (tmp_path / "private").exists()


def test_source_hash_damage_stops_before_any_copy(tmp_path):
    rows = inputs(tmp_path)
    Path(rows[-1]["path"]).write_bytes(b"wrong")
    with pytest.raises(AssertionError):
        stager.stage_copies(rows, tmp_path / "private", VERSION, publisher(), names, Guard())
    assert not (tmp_path / "private").exists()


def test_late_source_change_is_detected_before_copying_replaced_file(tmp_path):
    rows = inputs(tmp_path)
    class ChangeBeforeCopy:
        def check(self):
            Path(rows[0]["path"]).write_bytes(b"replaced after verification")
    with pytest.raises(ValueError, match="private_source_changed"):
        stager.stage_copies(rows, tmp_path / "private", VERSION, publisher(), names, ChangeBeforeCopy())
    assert not list((tmp_path / "private").rglob("*.apk"))


def test_existing_output_and_symlink_sources_are_never_overwritten(tmp_path):
    rows = inputs(tmp_path)
    output = tmp_path / "private"
    output.mkdir()
    (output / "keep.txt").write_text("keep")
    with pytest.raises(ValueError, match="private_fresh_output_required"):
        stager.stage_copies(rows, output, VERSION, publisher(), names, Guard())
    assert (output / "keep.txt").read_text() == "keep"
    path = Path(rows[0]["path"])
    target = path.with_suffix(".actual")
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(AssertionError):
        stager.stage_copies(rows, tmp_path / "other", VERSION, publisher(), names, Guard())


def test_same_run_metadata_and_all_existing_verifiers_precede_private_copies(tmp_path, monkeypatch):
    originals = inputs(tmp_path)
    by_name = {row["name"]: row for row in originals}
    events = []
    pub = publisher()
    def api(path):
        events.append(("GET", path))
        return {"event": "workflow_dispatch"} if path.endswith(str(RUN)) else {}
    pub.GitHub = lambda token, opener: SimpleNamespace(api=api)
    bindings = {role: {"artifact_id": index + 1, "archive_sha256": "b" * 64}
                for index, role in enumerate(JOBS)}
    def validate_run(build, jobs, artifacts, source, run):
        assert source == SOURCE and run == RUN
        events.append(("all-required-verified",))
        return bindings
    pub.validate_run = validate_run
    def extract(archive, directory, role, guard):
        directory.mkdir(exist_ok=True)
        shutil.copyfile(by_name[RAW[role]]["path"], directory / RAW[role])
        name = "platform-report.json" if role != "ios-unified" else RAW[role].replace(".ipa", ".report.json")
        (directory / name).write_text(json.dumps({"platform": role}))
        events.append(("extract", role))
    pub.extract_generic = extract
    pub.read_json = lambda path: json.loads(path.read_text())
    pub.validate_platform = lambda report, role, source: (events.append(("platform", role)) or report)
    pub.validate_platform_files = lambda directory, report, guard: {
        **by_name[RAW[report["platform"]]], "path": str(directory / RAW[report["platform"]])}
    pub.digest = digest
    pub.write_json = lambda path, value: path.write_text(json.dumps(value))
    pub.DATA_PIN = {"bytes": 123, "sha256": "c" * 64}
    pub.LOVE_SERVER_DATA = SimpleNamespace(load_pin=lambda: {"upgrade_proof": {"fixed": True}})
    pub.VERSION, pub.IPA_VERSION, pub.REPO = "0.3.36", "156.9116", "tagundo/IdolyPride_client"
    def fetch(binding, token, path, guard):
        assert token == "test-token"
        events.append(("fetch", binding["artifact_id"]))
        path.write_bytes(b"owned transport")
    def verify_ios(directory, proof, source, run, artifact, guard):
        events.append(("all-ios-gates",))
        return {"artifacts": [{**by_name[RAW["ios-unified"]], "path": str(directory / RAW["ios-unified"])}]}, None
    delivery = SimpleNamespace(Guard=Guard, OPENER=object(), fetch_archive=fetch,
        extract_archive=lambda archive, directory, binding, guard: extract(archive, directory, "ios-unified", guard),
        verify_members=verify_ios)
    monkeypatch.setattr(stager, "module", lambda name, path: names if path.endswith("release_identity.py")
        else delivery if path.endswith("delivery.py") else pub)
    result = stager.stage_candidate(SOURCE, RUN, VERSION, tmp_path / "work", tmp_path / "private", "test-token")
    assert result["status"] == "PASS_PRIVATE_CANDIDATE" and result["official_release_published"] is False
    assert result["input_artifacts"] == bindings and result["source_artifacts_preserved"] is True
    assert result["all_required_verification_jobs_passed"] is True
    assert result["required_verification_jobs"] == list(JOBS)
    assert "all_six_verification_jobs_passed" not in result and len(result["artifacts"]) == 2
    assert len([event for event in events if event[0] == "GET"]) == 3
    assert len([event for event in events if event[0] == "fetch"]) == 2
    assert ("all-required-verified",) in events and ("all-ios-gates",) in events
    assert ("platform", "android") in events and ("platform", "macos") not in events
    for row in result["artifacts"]:
        folder = tmp_path / "private" / row["artifact_directory"]
        assert {path.name for path in folder.iterdir()} == {row["name"], "SHA256SUMS", "PRIVATE-CANDIDATE.json", "README.txt"}
        assert (folder / "SHA256SUMS").read_text() == row["sha256"] + "  " + row["name"] + "\n"
        assert json.loads((folder / "PRIVATE-CANDIDATE.json").read_text())["artifacts"] == [row]
        assert (tmp_path / "work" / row["artifact_directory"] / row["source_name"]).is_file()
    assert all(Path(row["path"]).is_file() for row in originals)


def test_private_job_requires_every_gate_and_uses_read_only_separate_downloads():
    workflow = (ROOT / ".github/workflows/release-all-platforms.yml").read_text()
    job = workflow.split("\n  private-artifacts:\n", 1)[1].split("\n  publish:\n", 1)[0]
    assert "github.event_name == 'workflow_dispatch' && !inputs.publish" in job
    for role in JOBS:
        assert "needs." + role + ".result == 'success'" in job
    assert "actions: read" in job and "contents: read" in job and "contents: write" not in job
    assert job.count("uses: actions/upload-artifact@v4") == 2
    for role in RAW:
        assert "name: private-candidate-" + role + "-${{ inputs.release_version }}-${{ github.sha }}" in job
        assert "path: ${{ runner.temp }}/idoly-private-candidate/" + role in job
    tree = ast.parse((ROOT / "tools/stage_private_candidate.py").read_text())
    calls = [node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)]
    assert not set(calls) & {"publish", "main", "require_fresh", "companion", "upload", "create_release", "delete_release"}
    assert '--candidate-version "$IDOLY_RELEASE_VERSION"' in job


@pytest.mark.parametrize("kind", ["extra-mac-app", "missing-ipa", "dedicated-playcover-ipa"])
def test_retired_mac_deliverables_are_not_private_staging_targets(tmp_path, kind):
    rows = inputs(tmp_path)
    if kind == "missing-ipa":
        rows.pop()
    elif kind == "dedicated-playcover-ipa":
        rows[-1] = {**rows[-1], "name": "IdolyPride-6.1.1-Local-PlayCover-ko.ipa"}
    else:
        rows.append({**rows[0], "name": "IdolyPride-Local-Server-macOS-arm64.app.zip"})
    with pytest.raises(ValueError, match="private_primary_inventory_differs"):
        stager.stage_copies(rows, tmp_path / "private", VERSION, publisher(), names, Guard())
    assert not (tmp_path / "private").exists()


@pytest.mark.parametrize("kind", ["missing-required", "legacy-mac-role", "publisher-drops-required"])
def test_private_admission_requires_exact_current_job_bindings_before_fetch(tmp_path, monkeypatch, kind):
    pub = publisher()
    pub.GitHub = lambda *_: SimpleNamespace(api=lambda path: {"event": "workflow_dispatch"})
    bindings = {role: {} for role in JOBS}
    if kind == "missing-required":
        del bindings["portable"]
    elif kind == "legacy-mac-role":
        bindings["macos"] = {}
    else:
        pub.JOBS = JOBS[1:]
        del bindings["portable"]
    pub.validate_run = lambda *args: bindings
    delivery = SimpleNamespace(Guard=Guard, OPENER=object(),
        fetch_archive=lambda *args: pytest.fail("incomplete required jobs started a download"))
    monkeypatch.setattr(stager, "module", lambda name, path: names if path.endswith("release_identity.py")
        else delivery if path.endswith("delivery.py") else pub)
    with pytest.raises(ValueError, match="private_required_artifacts_differs"):
        stager.stage_candidate(SOURCE, RUN, VERSION, tmp_path / "work", tmp_path / "private", "test-token")
    assert not (tmp_path / "private").exists()


def workflow_job(workflow, name):
    jobs = workflow.split("\njobs:\n", 1)[1]
    match = re.search(r"(?ms)^  " + re.escape(name) + r":\n(.*?)(?=^  [a-z][a-z0-9-]*:\n|\Z)", jobs)
    assert match is not None
    return match.group(1)


def test_release_workflow_has_five_product_checks_and_retains_real_apple_runner():
    workflow = (ROOT / ".github/workflows/release-all-platforms.yml").read_text()
    jobs = workflow.split("\njobs:\n", 1)[1]
    assert set(re.findall(r"(?m)^  ([a-z][a-z0-9-]*):$", jobs)) == set(JOBS) | {"private-artifacts", "publish"}
    assert "runs-on: macos-15" in workflow_job(workflow, "ios-unified")
    assert "--platform macos" not in workflow
    assert "optimized-release-macos-" not in workflow and "private-candidate-macos-" not in workflow
    for name in ("private-artifacts", "publish"):
        job = workflow_job(workflow, name)
        needs = re.search(r"needs: \[([^\]]+)\]", job)
        assert needs and tuple(role.strip() for role in needs.group(1).split(",")) == JOBS
        condition = job.split("if: >-", 1)[1].split("runs-on:", 1)[0]
        assert set(re.findall(r"needs\.([a-z-]+)\.result == 'success'", condition)) == set(JOBS)
        assert len(re.findall(r"needs\.[a-z-]+\.result == 'success'", condition)) == 5
        assert "||" not in condition and "always()" not in condition and "skipped" not in condition
        assert "needs.macos" not in condition


def test_ios_compile_can_fetch_verified_lfs_object_with_step_scoped_token():
    workflow = (ROOT / ".github/workflows/release-all-platforms.yml").read_text()
    ios = workflow_job(workflow, "ios-unified")
    compile_step = ios.split("- name: Compile real Apple frameworks and run all five cold language launches", 1)[1].split("\n      - ", 1)[0]
    assert re.search(r"(?m)^        env:\n          GH_TOKEN: \$\{\{ github\.token \}\}$", compile_step)
    assert "python3 -B ios-unified/ci_build.py" in compile_step
    assert "GH_TOKEN" not in ios.split("steps:", 1)[0]
    verification_step = ios.split("- name: Verify host lifecycle, packaging, load gate and settings bridge", 1)[1].split("\n      - ", 1)[0]
    assert "GH_TOKEN" not in verification_step


def test_read_only_focused_naming_workflow_runs_the_product_scope_checks():
    workflow = (ROOT / ".github/workflows/verify-release-naming.yml").read_text()
    assert "      - tools/stage_private_candidate.py" in workflow
    assert "      - tests/test_stage_private_candidate.py" in workflow
    assert "          tests/test_stage_private_candidate.py" in workflow
    assert "contents: read" in workflow and "contents: write" not in workflow and "GH_TOKEN" not in workflow
