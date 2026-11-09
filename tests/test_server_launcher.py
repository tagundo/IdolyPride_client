import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
from unittest.mock import Mock

from google.protobuf import descriptor_pb2
import pytest

from idoly_local.profiles import new_profile
from idoly_local.schema import Schema
from idoly_local.state import State


PROJECT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("server_launcher", PROJECT / "tools/run_local_server.py")
launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(launcher)


def write_schema(output):
    file = descriptor_pb2.FileDescriptorProto(name="launcher-test.proto", package="api", syntax="proto3")
    file.message_type.add(name="Empty")
    user = file.message_type.add(name="Manager")
    user.field.add(name="name", number=1, type=9)
    user.field.add(name="managerLevel", number=100, type=5)
    response = file.message_type.add(name="UserGetResponse")
    response.field.add(name="user", number=1, type=11, type_name=".api.Manager")
    response.field.add(name="cards", number=3, type=9, label=3)
    file.service.add(name="System").method.add(name="Check", input_type=".api.Empty", output_type=".api.Empty")
    file.service.add(name="User").method.add(name="Get", input_type=".api.Empty", output_type=".api.UserGetResponse")
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(descriptors.SerializeToString())


def write_archive(output):
    (output / "assets/master").mkdir(parents=True, exist_ok=True)
    (output / "master-tag.json").write_text(json.dumps({"version": "fixture", "masterTagPacks": []}))


@pytest.fixture
def ready_data(tmp_path):
    data = tmp_path / "my data"
    write_schema(data / "protocol/idolypride-6.1.1.pb")
    write_archive(data / "original-master")
    return data


def test_existing_snapshot_identity_sessions_and_fixtures_are_preserved(ready_data, monkeypatch):
    schema = Schema.from_descriptor_set(ready_data / "protocol/idolypride-6.1.1.pb")
    state = State(ready_data / "state.db")
    response = schema.response_type("/api.User/Get")()
    response.user.name = "기존 매니저"
    response.user.managerLevel = 17
    response.cards.append("preserved-card")
    state.save_snapshot("sandbox", response.SerializeToString(), schema.fingerprint)
    token, identity = state.login("sandbox")
    before = state.snapshot("sandbox")
    fixtures = ready_data / "sandbox/fixtures"
    fixtures.mkdir(parents=True)
    marker = fixtures / "personal.pb"
    marker.write_bytes(b"preserve this capture")
    serve = Mock()
    archive = Mock(side_effect=AssertionError("Unexpected network collection"))
    extract = Mock(side_effect=AssertionError("Existing schema must not be replaced"))
    monkeypatch.setattr("idoly_local.cli.serve", serve)
    monkeypatch.setattr("idoly_local.collect.archive_public_master", archive)
    monkeypatch.setattr(launcher, "extract_schema", extract)
    args = launcher.parser().parse_args(["--data-dir", str(ready_data), "--manager-name", "replacement",
                                        "--client", "/missing-but-unused.ipa"])
    launcher.run(args)
    restarted = State(ready_data / "state.db")
    assert restarted.snapshot("sandbox") == before
    assert restarted.profile("sandbox") == identity
    assert restarted.authenticated(token, "sandbox")
    assert marker.read_bytes() == b"preserve this capture"
    archive.assert_not_called()
    extract.assert_not_called()
    options, loaded = serve.call_args.args
    assert loaded.fingerprint == schema.fingerprint
    assert options.bind == "127.0.0.1:50051"
    assert options.asset_base_url == "http://127.0.0.1:8080"
    assert options.fixtures == fixtures


def test_missing_snapshot_is_created_once_without_replacing_other_profiles(ready_data, monkeypatch):
    schema = Schema.from_descriptor_set(ready_data / "protocol/idolypride-6.1.1.pb")
    state = State(ready_data / "state.db")
    other = new_profile(state, schema, "other", "Keep other")
    serve = Mock()
    monkeypatch.setattr("idoly_local.cli.serve", serve)
    args = launcher.parser().parse_args(["--data-dir", str(ready_data), "--manager-name", "새 매니저"])
    launcher.run(args)
    snapshot = State(ready_data / "state.db").snapshot("sandbox")
    assert schema.response_type("/api.User/Get").FromString(snapshot[0]).user.name == "새 매니저"
    args.manager_name = "must not overwrite"
    launcher.run(args)
    assert State(ready_data / "state.db").snapshot("sandbox") == snapshot
    assert State(ready_data / "state.db").snapshot("other")[0] == other


def test_network_download_runs_only_on_explicit_flag(tmp_path, monkeypatch):
    data = tmp_path / "data"
    write_schema(data / "protocol/idolypride-6.1.1.pb")
    calls = []

    def archive(schema, output):
        calls.append(output)
        write_archive(output)

    monkeypatch.setattr("idoly_local.collect.archive_public_master", archive)
    monkeypatch.setattr("idoly_local.cli.serve", Mock())
    args = launcher.parser().parse_args(["--data-dir", str(data)])
    with pytest.raises(launcher.LauncherError, match="--download-master"):
        launcher.run(args)
    assert calls == []
    assert not (data / "state.db").exists()
    args.download_master = True
    launcher.run(args)
    assert calls == [data / "original-master"]
    assert State(data / "state.db").snapshot("sandbox") is not None


@pytest.mark.parametrize("suffix,script", [(".xapk", "extract_client_schema.py"),
                                         (".apk", "extract_client_schema.py"),
                                         (".ipa", "extract_ios_schema.py")])
def test_missing_schema_uses_the_matching_local_extractor_once(tmp_path, monkeypatch, suffix, script):
    data = tmp_path / "data"
    write_archive(data / "original-master")
    client = tmp_path / ("original client" + suffix)
    client.write_bytes(b"local fixture input")
    calls = []

    def extract(command, check):
        calls.append(command)
        assert check is True
        assert Path(command[1]).name == script
        assert command[2] == str(client)
        write_schema(Path(command[command.index("--output") + 1]))

    monkeypatch.setattr(launcher.subprocess, "run", extract)
    monkeypatch.setattr("idoly_local.cli.serve", Mock())
    args = launcher.parser().parse_args(["--data-dir", str(data), "--client", str(client)])
    launcher.run(args)
    launcher.run(args)
    assert len(calls) == 1
    assert client.read_bytes() == b"local fixture input"


def test_fresh_source_missing_client_has_actionable_error_without_data_changes(tmp_path, monkeypatch):
    data = tmp_path / "data"
    network = Mock(side_effect=AssertionError("Unexpected network collection"))
    monkeypatch.setattr("idoly_local.collect.archive_public_master", network)
    args = launcher.parser().parse_args(["--data-dir", str(data)])
    with pytest.raises(launcher.LauncherError, match="Supply --client"):
        launcher.run(args)
    assert not data.exists()
    network.assert_not_called()


def test_custom_ports_and_separate_profile_fixture_directory(ready_data, monkeypatch):
    serve = Mock()
    monkeypatch.setattr("idoly_local.cli.serve", serve)
    args = launcher.parser().parse_args(["--data-dir", str(ready_data), "--profile", "restored",
                                        "--grpc-port", "50505", "--asset-port", "8181"])
    launcher.run(args)
    options, _ = serve.call_args.args
    assert options.bind == "127.0.0.1:50505"
    assert options.asset_base_url == "http://127.0.0.1:8181"
    assert options.fixtures == ready_data / "restored/fixtures"


@pytest.mark.parametrize("arguments", [["--grpc-port", "0"], ["--asset-port", "65536"],
                                       ["--grpc-port", "invalid"], ["--profile", "../outside"]])
def test_invalid_port_or_profile_is_rejected(arguments):
    with pytest.raises(SystemExit) as failure:
        launcher.parser().parse_args(arguments)
    assert failure.value.code == 2


def test_missing_virtualenv_and_explicit_reexec_are_clear(tmp_path, monkeypatch):
    with pytest.raises(launcher.LauncherError, match="setup_local_server.sh"):
        launcher.ensure_environment(tmp_path, [])
    interpreter = tmp_path / ".venv/bin/python"
    interpreter.parent.mkdir(parents=True)
    interpreter.touch()
    invoked = []

    def execute(path, arguments):
        invoked.append((path, arguments))
        raise SystemExit(23)

    monkeypatch.setattr(launcher.os, "execv", execute)
    with pytest.raises(SystemExit) as failure:
        launcher.ensure_environment(tmp_path, ["--data-dir", "path with spaces"])
    assert failure.value.code == 23
    assert invoked == [(str(interpreter), [str(interpreter), str(tmp_path / "tools/run_local_server.py"),
                                          "--data-dir", "path with spaces"])]


@pytest.mark.parametrize("termux", [False, True])
def test_setup_shell_platform_flow_with_mocked_commands(tmp_path, termux):
    """Exercise the shell's command selection without installing any package."""
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    setup = project / "tools/setup_local_server.sh"
    shutil.copyfile(PROJECT / "tools/setup_local_server.sh", setup)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    log = tmp_path / "commands.log"
    python = fake_bin / "python"
    python.write_text('''#!/bin/sh
printf '%s|%s\\n' "$0" "$*" >> "$IDOLY_TEST_LOG"
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  for destination do :; done
  /bin/mkdir -p "$destination/bin"
  /bin/cp "$0" "$destination/bin/python"
fi
''')
    python.chmod(0o755)
    (fake_bin / "python3").symlink_to(python)
    pkg = fake_bin / "pkg"
    pkg.write_text('#!/bin/sh\nprintf "pkg|%s\\n" "$*" >> "$IDOLY_TEST_LOG"\n')
    pkg.chmod(0o755)
    uname = fake_bin / "uname"
    uname.write_text('#!/bin/sh\nprintf "Darwin\\n"\n')
    uname.chmod(0o755)
    environment = os.environ.copy()
    environment.pop("TERMUX_VERSION", None)
    environment.pop("PREFIX", None)
    environment.pop("IDOLY_PYTHON", None)
    environment.update(PATH=str(fake_bin) + os.pathsep + environment["PATH"], IDOLY_TEST_LOG=str(log))
    if termux:
        environment["TERMUX_VERSION"] = "fixture"
    subprocess.run(["bash", "-n", str(setup)], check=True)
    subprocess.run(["bash", str(setup)], check=True, env=environment, capture_output=True, text=True)
    commands = log.read_text()
    assert ".venv/bin/python|-m pip install -e " + str(project) + "[extract]" in commands
    assert "--upgrade" not in commands
    if termux:
        assert "pkg|install python python-grpcio capstone clang make" in commands
        assert "-m venv --system-site-packages .venv" in commands
    else:
        assert "pkg|" not in commands
        assert "-m venv .venv" in commands
