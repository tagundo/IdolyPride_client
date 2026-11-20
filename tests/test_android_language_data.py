"""Cold-start locale transport preserves actual Unity ZIP bytes and shares spans."""
from io import BytesIO
from copy import copy
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
from zipfile import ZipFile, ZIP_DEFLATED, ZIP_STORED
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("android_language_data_test", ROOT / "tools/build_android_language_data.py")
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
JAVA = ROOT / "android-server/app/src/main/java/game/qualiarts/idolypride/localserver/UnifiedGameZip.java"
STATE = JAVA.with_name("UnifiedGamePreparation.java")


@pytest.fixture
def inputs(tmp_path):
    clients = {}
    for language in tool.LANGUAGES:
        path = tmp_path / (language + ".apk")
        with ZipFile(path, "x") as archive:
            archive.writestr("classes.dex", b"retained game code", compress_type=ZIP_DEFLATED)
            archive.writestr(tool.PREFIX + "boot.config", b"same boot configuration", compress_type=ZIP_DEFLATED)
            archive.writestr(tool.PREFIX + "common.resource", b"unchanged common texture" * 400, compress_type=ZIP_STORED)
            archive.writestr(tool.PREFIX + "Managed/Metadata/global-metadata.dat", b"native metadata " + language.encode(), compress_type=ZIP_DEFLATED)
            archive.writestr(tool.PREFIX + "unity_app_guid", (language * 16).encode(), compress_type=ZIP_DEFLATED)
            archive.writestr(tool.PREFIX + "localized.assets", b"shared ja/en" if language != "ko" else b"korean", compress_type=ZIP_DEFLATED)
            for name in tool.STATIC_ASSETS:
                archive.writestr(name, ("retained original static asset " + name).encode(), compress_type=ZIP_DEFLATED)
        clients[language] = path
    return clients


def build(inputs, tmp_path):
    output = tmp_path / "language.zip"
    descriptor = tool.build_archive(inputs, output, pins={lang: tool.record(path) for lang, path in inputs.items()})
    return output, descriptor


def rewrite(path, edits):
    with ZipFile(path) as source:
        rows = {entry.filename: (entry, source.read(entry)) for entry in source.infolist()}
    with ZipFile(path, "w") as target:
        for name, (entry, raw) in rows.items():
            target.writestr(entry, edits.pop(name, raw))
        for name, raw in edits.items():
            target.writestr(name, raw)


def test_three_languages_share_common_data_and_deduplicate_extra_encoded_spans(inputs, tmp_path):
    output, descriptor = build(inputs, tmp_path)
    assert descriptor["asset"] == "idoly-unified/game-data.json"
    assert descriptor["languages"] == ["ko", "ja", "en"]
    with ZipFile(output) as archive:
        index = json.loads(archive.read(tool.INDEX))
        rows = {lang: {row["name"]: row for row in data["entries"]} for lang, data in index["languages"].items()}
        assert rows["ja"][tool.PREFIX + "localized.assets"]["source"] == rows["en"][tool.PREFIX + "localized.assets"]["source"]
        assert all(rows[lang][tool.PREFIX + "common.resource"]["source"]["kind"] == "base" for lang in tool.LANGUAGES)
        assert all(info.compress_type == ZIP_STORED for info in archive.infolist())
        assert not any(name.endswith((".dex", ".so")) for name in archive.namelist())
    assert tool.validate_data_archive(output, inputs["ko"]) == descriptor


def test_carrier_is_complete_plain_zip_with_original_language_bytes(inputs, tmp_path):
    output, _ = build(inputs, tmp_path)
    with ZipFile(output) as extras, ZipFile(inputs["ko"]) as base:
        index = json.loads(extras.read(tool.INDEX))
        for language in tool.LANGUAGES:
            stream = BytesIO()
            def read(row):
                source = row["source"]
                return tool.encoded(base, base.getinfo(source["member"])) if source["kind"] == "base" else extras.read(source["member"])
            tool.carrier(index["languages"][language]["entries"], read, stream.write)
            with ZipFile(BytesIO(stream.getvalue())) as selected, ZipFile(inputs[language]) as original:
                assert selected.testzip() is None
                assert set(selected.namelist()) == {name for name in original.namelist() if tool.carrier_member(name)}
                assert all(selected.read(name) == original.read(name) for name in selected.namelist())
                assert all(selected.getinfo(name).compress_type == original.getinfo(name).compress_type for name in selected.namelist())


@pytest.mark.parametrize("change", ["code", "boot", "missing", "wrong-pin"])
def test_inputs_reject_locale_code_changes_and_incomplete_data(inputs, tmp_path, change):
    pins = {lang: tool.record(path) for lang, path in inputs.items()}
    if change == "code": rewrite(inputs["ja"], {"classes.dex": b"different code"})
    if change == "boot": rewrite(inputs["en"], {tool.PREFIX + "boot.config": b"different boot"})
    if change == "missing": rewrite(inputs["ja"], {tool.PREFIX + "extra": b"new file"})
    if change != "wrong-pin": pins = {lang: tool.record(path) for lang, path in inputs.items()}
    else: pins["en"]["sha256"] = "0" * 64
    with pytest.raises(ValueError): tool.build_archive(inputs, tmp_path / "bad.zip", pins=pins)
    assert not (tmp_path / "bad.zip").exists() and not (tmp_path / "bad.zip.partial").exists()


@pytest.mark.parametrize("change", ["extra-code", "corrupt-object", "forged-carrier", "missing-object"])
def test_archive_admission_rejects_unreferenced_code_and_tampering(inputs, tmp_path, change):
    output, _ = build(inputs, tmp_path)
    with ZipFile(output) as source:
        members = {info.filename: source.read(info) for info in source.infolist()}
    if change == "extra-code": members["classes.dex"] = b"not allowed"
    elif change == "corrupt-object": members[next(name for name in members if name != tool.INDEX)] += b"broken"
    elif change == "missing-object": del members[next(name for name in members if name != tool.INDEX)]
    else:
        index = json.loads(members[tool.INDEX]); index["languages"]["en"]["carrier"]["sha256"] = "0" * 64
        members[tool.INDEX] = tool.json_bytes(index)
    with ZipFile(output, "w") as target:
        for name, raw in members.items(): target.writestr(name, raw)
    with pytest.raises((ValueError, KeyError, zlib.error)):
        tool.validate_data_archive(output, inputs["ko"])


@pytest.fixture(scope="module")
def java_runner(tmp_path_factory):
    if not shutil.which("javac") or not shutil.which("java"): pytest.skip("JDK unavailable")
    work = tmp_path_factory.mktemp("language-java")
    harness = work / "LanguageZipHost.java"
    harness.write_text('''package game.qualiarts.idolypride.localserver;
import java.io.*; import java.nio.file.*; import java.util.*;
public final class LanguageZipHost {
 public static void main(String[] args) throws Exception {
  if (args[0].equals("whitelist")) { for (String name:new TreeSet<>(UnifiedGameZip.STATIC_ASSETS)) System.out.println(name); return; }
  if (args[0].equals("concurrency")) {
   UnifiedGamePreparation state=new UnifiedGamePreparation();
   UnifiedGamePreparation.Snapshot ko=new UnifiedGamePreparation.Snapshot("ko","/verified/ko.zip","ko-identity",77);
   UnifiedGamePreparation.Snapshot ja=new UnifiedGamePreparation.Snapshot("ja","/prepared/ja.zip","ja-identity",76);
   state.publish(ko,false,()->{});
   java.util.concurrent.CountDownLatch entered=new java.util.concurrent.CountDownLatch(1), release=new java.util.concurrent.CountDownLatch(1);
   java.util.concurrent.atomic.AtomicBoolean rejected=new java.util.concurrent.atomic.AtomicBoolean(false), committed=new java.util.concurrent.atomic.AtomicBoolean(false);
   Thread worker=new Thread(()->{ synchronized(state.workerLock) {
    entered.countDown(); try { release.await(); state.publish(ja,true,()->committed.set(true)); }
    catch(Exception expected) { rejected.set(expected.getMessage().equals("unified_data_cold_restart_required")); }
   }}); worker.start();
   if(!entered.await(2,java.util.concurrent.TimeUnit.SECONDS)) throw new AssertionError("worker did not start");
   if(!state.isPrepared("ko") || state.ready()!=ko || state.frozenLanguage()!=null || !state.freeze("ko").equals(ko.path)) throw new AssertionError("UI snapshot unavailable");
   // These real state accessors must complete while a preparation worker is held.
   for(int n=0;n<1000;n++) if(!state.isPrepared("ko") || state.frozen()!=ko || !state.frozenLanguage().equals("ko") || !state.freeze("ko").equals(ko.path)) throw new AssertionError("frozen snapshot changed");
   release.countDown(); worker.join(2000);
   if(worker.isAlive() || !rejected.get() || committed.get() || state.ready()!=ko) throw new AssertionError("publication race replaced live carrier");
   if(state.publish(new UnifiedGamePreparation.Snapshot("ko",ko.path,ko.identity,ko.bytes),false,()->{})) throw new AssertionError("active publication declared cold");
   UnifiedGamePreparation cold=new UnifiedGamePreparation(); cold.publish(ko,false,()->{});
   try { cold.publish(ja,true,()->{throw new IOException("rename-failed");}); throw new AssertionError("expected failure"); }
   catch(IOException expected) { if(!expected.getMessage().equals("rename-failed")) throw expected; }
   if(cold.ready()!=ko || cold.frozen()!=null) throw new AssertionError("failed publication lost old carrier");
   return;
  }
  if (args[0].equals("inspect")) { try (UnifiedGameZip.Source ignored = new UnifiedGameZip.Source(new File(args[1]))) {} return; }
  List<UnifiedGameZip.Entry> entries = new ArrayList<>();
  for(String line:Files.readAllLines(Paths.get(args[2]))) { String[] f=line.split("\\t");
   entries.add(new UnifiedGameZip.Entry(f[0],f[1],f[2].equals("object"),Long.parseLong(f[3]),Long.parseLong(f[4]),Long.parseLong(f[5]),Integer.parseInt(f[6]),f[7])); }
  try (UnifiedGameZip.Source source = new UnifiedGameZip.Source(new File(args[1]))) {
   UnifiedGameZip.assemble(source,entries,new File(args[3]),Long.parseLong(args[4]),args[5]); }
 }
}''')
    subprocess.run(["javac", "-d", str(work), str(JAVA), str(STATE), str(harness)], check=True, capture_output=True)
    return ["java", "-Xmx128m", "-cp", str(work), "game.qualiarts.idolypride.localserver.LanguageZipHost"]


def test_java_runtime_produces_the_exact_canonical_language_archive(inputs, tmp_path, java_runner):
    output, _ = build(inputs, tmp_path)
    installed = tmp_path / "installed.apk"
    with ZipFile(inputs["ko"]) as base, ZipFile(output) as extra, ZipFile(installed, "w") as target:
        index = json.loads(extra.read(tool.INDEX))
        for archive in (base, extra):
            for row in archive.infolist(): target.writestr(copy(row), archive.read(row))
    assert tool.validate_data_archive(installed, inputs["ko"], embedded=True)["sha256"]
    for language in tool.LANGUAGES:
        data = index["languages"][language]
        tsv = tmp_path / (language + ".tsv")
        tsv.write_text("\n".join("\t".join(map(str, [row["name"], row["source"]["member"], row["source"]["kind"], row["bytes"], row["compressed_bytes"], row["crc32"], row["method"], row["compressed_sha256"]])) for row in data["entries"]))
        selected = tmp_path / (language + "-selected.zip")
        subprocess.run(java_runner + ["assemble", str(installed), str(tsv), str(selected), str(data["carrier"]["bytes"]), data["carrier"]["sha256"]], check=True, capture_output=True)
        assert tool.record(selected) == data["carrier"]
        with ZipFile(selected) as archive, ZipFile(inputs[language]) as original:
            assert all(archive.read(name) == original.read(name) for name in archive.namelist())


def test_java_rejects_mismatched_local_headers(inputs, tmp_path, java_runner):
    source = inputs["ko"]
    raw = bytearray(source.read_bytes()); raw[8] = 0 if raw[8] != 0 else 8
    source.write_bytes(raw)
    result = subprocess.run(java_runner + ["inspect", str(source)], capture_output=True, text=True)
    assert result.returncode != 0 and "unified_zip_local_differs" in result.stderr


def test_embedded_archive_rejects_recompressed_or_corrupted_base_spans(inputs, tmp_path):
    output, _ = build(inputs, tmp_path)
    installed = tmp_path / "embedded.apk"
    with ZipFile(inputs["ko"]) as base, ZipFile(output) as extra, ZipFile(installed, "w") as target:
        for archive in (base, extra):
            for row in archive.infolist():
                value = archive.read(row)
                if row.filename == tool.PREFIX + "common.resource": value = b"x" + value[1:]
                target.writestr(copy(row), value)
    with pytest.raises(ValueError, match="language_base_encoding_differs|language_object_integrity_differs|language_source_span_differs"):
        tool.validate_data_archive(installed, inputs["ko"], embedded=True)


def test_extraction_guid_must_change_when_switching_language(inputs, tmp_path):
    with ZipFile(inputs["ko"]) as base: guid = base.read(tool.PREFIX + "unity_app_guid")
    rewrite(inputs["ja"], {tool.PREFIX + "unity_app_guid": guid})
    with pytest.raises(ValueError, match="language_extraction_guids_not_distinct"):
        build(inputs, tmp_path)


def test_ui_snapshots_and_freeze_do_not_wait_for_a_worker_or_publish_over_a_live_session(java_runner):
    subprocess.run(java_runner + ["concurrency"], check=True, capture_output=True, timeout=8)


def test_java_and_python_share_the_exact_static_asset_allowlist(java_runner):
    result = subprocess.run(java_runner + ["whitelist"], check=True, capture_output=True, text=True)
    assert result.stdout.splitlines() == sorted(tool.STATIC_ASSETS)
    assert len(tool.STATIC_ASSETS) == 46
    assert not any(name.endswith((".dex", ".so", ".prof", ".profm")) for name in tool.STATIC_ASSETS)


def test_static_assets_are_copied_but_must_be_identical_in_every_locale(inputs, tmp_path):
    output, _ = build(inputs, tmp_path)
    with ZipFile(output) as archive:
        index = json.loads(archive.read(tool.INDEX))
        for data in index["languages"].values():
            by_name = {row["name"]: row for row in data["entries"]}
            assert set(tool.STATIC_ASSETS) <= set(by_name)
            assert all(by_name[name]["source"]["kind"] == "base" for name in tool.STATIC_ASSETS)
    rewrite(inputs["en"], {"assets/WebView/Inquiry.html": b"changed UI code"})
    with pytest.raises(ValueError, match="language_non_data_member_differs"):
        tool.build_archive(inputs, tmp_path / "changed.zip", pins={lang: tool.record(path) for lang, path in inputs.items()})
