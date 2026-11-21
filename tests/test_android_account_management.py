"""Native account picker/lifecycle boundaries and exact Java stream implementation.

The bridge tests never start a server. The host harness compiles the production
AccountTransfers class against minimal Android API seams and exercises real files.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver"
BRIDGE = ROOT / "android-server/app/src/main/python/android_server_runtime.py"


@pytest.fixture
def native(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("android_account_boundary", BRIDGE)
    boundary = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(boundary)
    files = tmp_path / "files"
    (files / "data").mkdir(parents=True)
    calls = []
    monkeypatch.setenv("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")
    def command(root, action, payload):
        calls.append((root, action, payload))
        return {"schema": 1, "ok": True, "action": action, "status": {"accounts": []}}
    def settings(root):
        calls.append(("settings", root))
        return {"startup_checks": {"scope": "previous_run"}, "durable_history": {"retained_records": 3}}
    def clear(root):
        calls.append(("clear", root))
        return {"retained_records": 0}
    monkeypatch.setitem(sys.modules, "idoly_local.account_manager", SimpleNamespace(account_command=command))
    monkeypatch.setitem(sys.modules, "idoly_local.app_runtime", SimpleNamespace(
        server_settings_status=settings, clear_server_history=clear))
    def invoke(action, payload=None):
        return json.loads(boundary.management_command_json(str(files), action, json.dumps(payload or {})))
    return boundary, files, calls, invoke


class ActiveRuntime:
    def __init__(self, mode="normal"):
        self.mode, self.cleared = mode, False
    def status(self):
        return {"running": True, "profile": "active", "media_mode": self.mode == "media",
                "startup_checks": {"scope": "current_run"},
                "durable_history": {"retained_records": 0 if self.cleared else 7}}
    def clear_history(self):
        self.cleared = True


@pytest.mark.parametrize("action,payload", [
    ("accounts_import", {"mode": "normal", "profile": "active", "replace": True}),
    ("accounts_restore", {"mode": "normal", "profile": "active", "id": "a"*32}),
])
def test_active_profile_replacement_stops_before_backend_cached_identity_changes(native, action, payload):
    boundary, files, calls, invoke = native
    boundary._RUNTIME = ActiveRuntime()
    assert invoke(action, payload) == {"schema": 1, "ok": False, "error": "account_active_restart_required"}
    assert calls == []


@pytest.mark.parametrize("action,payload", [
    ("accounts_import", {"mode": "normal", "profile": "new", "replace": False}),
    ("accounts_import", {"mode": "normal", "profile": "other", "replace": True}),
    ("accounts_restore", {"mode": "media", "profile": "active", "id": "a"*32}),
    ("accounts_clone", {"mode": "normal", "source_profile": "active", "profile": "clone"}),
    ("accounts_export", {"mode": "normal", "profile": "active"}),
    ("accounts_select", {"mode": "normal", "profile": "other"}),
])
def test_new_target_reads_and_queued_selection_do_not_require_stopping_active_game(native, action, payload):
    boundary, files, calls, invoke = native
    boundary._RUNTIME = ActiveRuntime()
    result = invoke(action, payload)
    assert result["ok"] is True
    assert calls == [(files/"data", action, payload)]
    assert result["active"] == {"running": True, "mode": "normal", "profile": "active"}


@pytest.mark.parametrize("case", ["outside", "symlink", "hardlink", "wrong_name", "empty", "oversize", "inbox_symlink"])
def test_picker_preview_accepts_only_owned_bounded_regular_copies(native, tmp_path, case):
    boundary, files, calls, invoke = native
    inbox = files/"data/account-management/inbox"
    inbox.mkdir(parents=True)
    source = inbox/("account-import-" + "a"*32 + ".zip")
    source.write_bytes(b"PK\x03\x04backup")
    if case == "outside":
        source = tmp_path/source.name
        source.write_bytes(b"PK\x03\x04outside")
    elif case == "symlink":
        target = tmp_path/"original"
        source.rename(target)
        source.symlink_to(target)
    elif case == "hardlink":
        os.link(source, tmp_path/"another-link")
    elif case == "wrong_name":
        source.rename(inbox/"resource.zip")
        source = inbox/"resource.zip"
    elif case == "empty":
        source.write_bytes(b"")
    elif case == "oversize":
        with source.open("wb") as stream:
            stream.truncate(128 * 1024 * 1024 + 1)
    else:
        target = tmp_path/"linked-inbox"
        inbox.rename(target)
        inbox.symlink_to(target, target_is_directory=True)
    result = invoke("accounts_preview", {"path": str(source)})
    assert result["ok"] is False and result["error"] == "account_import_path_invalid"
    assert calls == []


def test_approved_preview_passes_one_private_copy_without_exposing_provider_uri(native):
    boundary, files, calls, invoke = native
    source = files/"data/account-management/inbox"/("account-import-" + "a"*32 + ".zip")
    source.parent.mkdir(parents=True)
    source.write_bytes(b"PK\x03\x04account")
    assert invoke("accounts_preview", {"path": str(source)})["ok"] is True
    assert calls == [(files/"data", "accounts_preview", {"path": str(source)})]


def test_settings_uses_live_observations_and_clear_keeps_same_runtime(native):
    boundary, files, calls, invoke = native
    current = ActiveRuntime()
    boundary._RUNTIME = current
    result = invoke("server_settings_status")
    assert result["settings"]["startup_checks"]["scope"] == "current_run"
    assert result["settings"]["durable_history"]["retained_records"] == 7
    assert invoke("server_history_clear")["settings"]["durable_history"]["retained_records"] == 0
    assert current.cleared and boundary._RUNTIME is current and calls == []


def test_stopped_settings_reads_prior_record_and_explicit_clear_only(native):
    boundary, files, calls, invoke = native
    result = invoke("server_settings_status")
    assert result["settings"]["startup_checks"]["scope"] == "previous_run"
    assert calls == [("settings", files/"data")]
    calls.clear()
    assert invoke("server_history_clear")["ok"] is True
    assert calls == [("clear", files/"data"), ("settings", files/"data")]


@pytest.mark.parametrize("action,payload", [("delete_all", {}), ("accounts_status", []),
    ("accounts_status", "not-json"), ("server_history_clear", {"path": "/private"}),
    ("accounts_status", "x"*8193)])
def test_native_requests_are_bounded_and_unknown_actions_cannot_reach_account_store(native, action, payload):
    boundary, files, calls, invoke = native
    encoded = json.dumps(payload) if not isinstance(payload, str) else payload
    result = json.loads(boundary.management_command_json(str(files), action, encoded))
    assert result["ok"] is False and result["error"] == "account_request_invalid"
    assert calls == []


def test_backend_errors_do_not_echo_private_paths_or_request_fields(native, monkeypatch):
    boundary, files, calls, invoke = native
    def fail(*args):
        raise ValueError("/private/manager-name/account.db password=secret")
    monkeypatch.setitem(sys.modules, "idoly_local.account_manager", SimpleNamespace(account_command=fail))
    result = invoke("accounts_create", {"manager_name": "private-name"})
    assert result == {"schema": 1, "ok": False, "error": "account_operation_failed"}


def test_account_surface_keeps_single_launch_and_account_resource_exports_separate():
    activity = (JAVA/"MainActivity.java").read_text()
    assert activity.count("Button launch = button(R.string.launch_diagnostic_client)") == 1
    for identifier in ["idoly.accounts.list", "idoly.accounts.create", "idoly.accounts.clone",
                       "idoly.accounts.select", "idoly.accounts.export", "idoly.accounts.import",
                       "idoly.accounts.restore", "idoly.accounts.profile-input"]:
        assert identifier in activity
    assert "requestReplaceAccountImport" in activity and "activeAccountTarget" in activity
    assert "pendingAccountPreview" in activity and "selection_revision" in activity
    assert "EXPORT_ACCOUNT" in activity and "EXPORT_RESOURCES" in activity
    assert "server_checks_previous" in activity


def test_production_account_document_streams_with_real_files_and_android_api_seams(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("Java host tools unavailable; mandatory in the release Linux runner")
    sources = {
        "android/net/Uri.java": """package android.net;
public final class Uri { private final String scheme; public Uri(String value){scheme=value;}
public String getScheme(){return scheme;} }""",
        "android/os/SystemClock.java": """package android.os;
public final class SystemClock { public static long uptimeMillis(){return System.nanoTime()/1000000;} }""",
        "android/content/ContentResolver.java": """package android.content;
import java.io.*; import android.net.Uri;
public class ContentResolver {
 public InputStream input; public OutputStream output;
 public InputStream openInputStream(Uri uri)throws IOException{return input;}
 public OutputStream openOutputStream(Uri uri,String mode)throws IOException{return output;}
}""",
        "android/content/Context.java": """package android.content;
import java.io.File;
public class Context { private final File files; public final ContentResolver resolver=new ContentResolver();
 public Context(File value){files=value;} public File getFilesDir(){return files;}
 public ContentResolver getContentResolver(){return resolver;}
}""",
        "game/qualiarts/idolypride/localserver/AccountTransfersHostTest.java": _JAVA_HARNESS,
    }
    paths = []
    for name, content in sources.items():
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        paths.append(str(path))
    classes = tmp_path/"classes"
    flags = ["-Xms16m", "-Xmx64m", "-Xss256k", "-XX:+UseSerialGC", "-XX:ActiveProcessorCount=1",
             "-XX:MaxMetaspaceSize=48m", "-XX:CompressedClassSpaceSize=8m", "-XX:ReservedCodeCacheSize=16m"]
    env = dict(os.environ)
    for key in ("JAVA_TOOL_OPTIONS", "_JAVA_OPTIONS", "JDK_JAVA_OPTIONS", "CLASSPATH", "JAVA_OPTS"): env.pop(key, None)
    subprocess.run([javac, *("-J" + flag for flag in flags), "-encoding", "UTF-8", "-d", str(classes),
                    str(JAVA/"AccountTransfers.java"), *paths], check=True, capture_output=True, timeout=60, env=env)
    result = subprocess.run([java, *flags, "-cp", str(classes),
        "game.qualiarts.idolypride.localserver.AccountTransfersHostTest", str(tmp_path/"files")],
        check=True, capture_output=True, text=True, timeout=60, env=env)
    assert result.stdout.strip() == "ACCOUNT_TRANSFERS_HOST_PASS"


_JAVA_HARNESS = r"""
package game.qualiarts.idolypride.localserver;
import android.content.Context; import android.net.Uri;
import java.io.*; import java.nio.file.*; import java.security.MessageDigest; import java.util.Arrays;
public final class AccountTransfersHostTest {
 interface Failing { void run() throws Exception; }
 static void check(boolean good,String name){if(!good)throw new AssertionError(name);}
 static void rejected(Failing action)throws Exception {boolean failed=false;try{action.run();}catch(IOException expected){failed=true;}check(failed,"must reject");}
 static String sha(byte[] value)throws Exception {StringBuilder out=new StringBuilder();for(byte b:MessageDigest.getInstance("SHA-256").digest(value))out.append(String.format("%02x",b&255));return out.toString();}
 public static void main(String[] args)throws Exception {
  File root=new File(args[0]);root.mkdirs();Context context=new Context(root);Uri uri=new Uri("content");
  byte[] body=new byte[256*1024+7];Arrays.fill(body,(byte)17);body[0]='P';body[1]='K';
  long[] progress={0,0};AccountTransfers.Progress observer=(phase,bytes,total)->{progress[0]++;progress[1]=bytes;};
  context.resolver.input=new ByteArrayInputStream(body);
  File copied=AccountTransfers.stage(context,uri,observer);
  check(copied.getName().matches("account-import-[0-9a-f]{32}\\.zip"),"private input name");
  check(Arrays.equals(Files.readAllBytes(copied.toPath()),body),"copied exact bytes");
  check(progress[0]>0&&progress[1]==body.length,"progress reaches actual byte count");
  rejected(()->AccountTransfers.stage(context,new Uri("file"),observer));
  long existing=Files.list(copied.getParentFile().toPath()).count();
  context.resolver.input=new ByteArrayInputStream(new byte[0]);
  rejected(()->AccountTransfers.stage(context,uri,observer));
  check(Files.list(copied.getParentFile().toPath()).count()==existing,"failed copy removes only new temporary");
  context.resolver.input=new InputStream(){long remaining=AccountTransfers.MAX_ARCHIVE_BYTES+1;
   public int read(){return remaining-- > 0 ? 0 : -1;}
   public int read(byte[] b,int off,int len){if(remaining<=0)return -1;int n=(int)Math.min(remaining,len);remaining-=n;return n;}};
  rejected(()->AccountTransfers.stage(context,uri,observer));
  check(Files.list(copied.getParentFile().toPath()).count()==existing,"oversized input cleans temporary");
  File exports=new File(root,"data/account-management/exports");exports.mkdirs();
  File account=new File(exports,"IdolyPride-Account-"+String.join("",java.util.Collections.nCopies(32,"a"))+".zip");
  Files.write(account.toPath(),body);String hash=sha(body);
  rejected(()->AccountTransfers.approvedExport(context,copied.getAbsolutePath()));
  File link=new File(exports,"IdolyPride-Account-"+String.join("",java.util.Collections.nCopies(32,"b"))+".zip");
  Files.createSymbolicLink(link.toPath(),account.toPath());rejected(()->AccountTransfers.approvedExport(context,link.getAbsolutePath()));
  context.resolver.output=new ByteArrayOutputStream();
  rejected(()->AccountTransfers.save(context,uri,account.getAbsolutePath(),body.length-1,hash,observer));
  check(account.isFile(),"wrong size retains source");
  context.resolver.output=new ByteArrayOutputStream();
  rejected(()->AccountTransfers.save(context,uri,account.getAbsolutePath(),body.length,"0".repeat(64),observer));
  check(account.isFile(),"digest failure retains source");
  ByteArrayOutputStream saved=new ByteArrayOutputStream();context.resolver.output=saved;
  AccountTransfers.save(context,uri,account.getAbsolutePath(),body.length,hash,observer);
  check(Arrays.equals(saved.toByteArray(),body),"export exact bytes");check(!account.exists(),"successful export consumes owned temp");
  AccountTransfers.discardExport(context,copied.getAbsolutePath());check(copied.isFile(),"discard cannot delete inbox/unrelated input");
  System.out.println("ACCOUNT_TRANSFERS_HOST_PASS");
 }
}
"""


def test_first_install_management_prepares_only_pinned_public_inputs_without_starting_server(native, monkeypatch):
    boundary, files, calls, invoke = native
    copied, installed = [], []
    payload_sha256, payload_bytes = "a" * 64, 345678
    config = SimpleNamespace(SERVER_DATA_SHA256=payload_sha256, SERVER_DATA_BYTES=payload_bytes)
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name: config))
    monkeypatch.setattr(boundary, "_copy_asset", lambda assets, target, digest: copied.append((assets, target, digest)))
    def install_bundle(bundle, root, digest, size):
        installed.append((bundle, root, digest, size))
        return root / "data"
    monkeypatch.setattr(boundary, "install_bundle", install_bundle)
    assets = object()
    result = json.loads(boundary.management_command_json(str(files), "accounts_create", "{}", assets))
    assert result["ok"] is True and boundary._RUNTIME is None
    assert copied == [(assets, files/"bundled-server-data.zip", payload_sha256)]
    assert installed == [(files/"bundled-server-data.zip", files, payload_sha256, payload_bytes)]
    assert type(installed[0][3]) is int
    assert calls[0] == (files/"data", "accounts_create", {})


def test_prepared_management_inputs_do_not_reopen_assets_or_start_listeners(native, monkeypatch):
    boundary, files, calls, invoke = native
    (files/"data/protocol").mkdir()
    (files/"data/protocol/idolypride-6.1.1.pb").write_bytes(b"fixture descriptor")
    (files/"data/master-json").mkdir()
    monkeypatch.setattr(boundary, "_copy_asset", lambda *args: pytest.fail("Prepared data must not recopy assets"))
    result = json.loads(boundary.management_command_json(str(files), "accounts_create", "{}", object()))
    assert result["ok"] is True and boundary._RUNTIME is None


def test_first_install_invalid_payload_identity_never_copies_or_changes_account(native, monkeypatch):
    boundary, files, calls, invoke = native
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name: SimpleNamespace(SERVER_DATA_SHA256="bad")))
    monkeypatch.setattr(boundary, "_copy_asset", lambda *args: pytest.fail("Invalid pin must not copy bytes"))
    result = json.loads(boundary.management_command_json(str(files), "accounts_create", "{}", object()))
    assert result == {"schema": 1, "ok": False, "error": "account_payload_identity_invalid"}
    assert calls == []
