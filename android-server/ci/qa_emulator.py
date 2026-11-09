#!/usr/bin/env python3
"""Exercise the native Android server UI and real encrypted loopback RPCs.

Only an emulator target is accepted. UI taps use fresh uiautomator node bounds;
screenshots, UI XML, logcat and a credential-free result report are retained.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

import grpc

from idoly_local import codec
from idoly_local.schema import Schema


PACKAGE = "game.qualiarts.idolypride.localserver"
ACTIVITY = PACKAGE + "/.MainActivity"
LOCAL_REFUND_DATE = 4102444800000  # 2100-01-01 UTC, safely convertible to JST.
PHOTO_CHARACTERS = ("char-ktn", "char-ngs", "char-mei", "char-suz", "char-ski")
STARTER_CHARACTERS = frozenset(("char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr",
    *PHOTO_CHARACTERS, "char-rei", "char-rio", "char-rui", "char-skr", "char-smr", "char-szk", "char-yu"))
PRIVATE_DATABASE = "files/data/state.db"
PRESERVED_TABLES = ("profiles", "sessions", "profile_settings")


class QA:
    def __init__(self, adb, serial, artifacts):
        self.command = [adb, "-s", serial]
        self.artifacts = artifacts
        artifacts.mkdir(parents=True, exist_ok=True)
        self.forwarded = []

    def adb(self, *args, binary=False, check=True):
        # A cold 98 MB install may compile DEX under software CPU emulation.
        timeout = 300 if args and args[0] == "install" else 90
        result = subprocess.run([*self.command, *args], capture_output=True, text=not binary, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError("adb command failed: " + " ".join(args[:3]))
        return result.stdout

    def capture(self, stage):
        raw = self.adb("exec-out", "uiautomator", "dump", "/dev/tty")
        begin, end = raw.find("<hierarchy"), raw.rfind("</hierarchy>")
        if begin < 0 or end < 0:
            raise RuntimeError("uiautomator did not return a UI hierarchy")
        xml = raw[begin:end + len("</hierarchy>")]
        (self.artifacts / (stage + ".xml")).write_text(xml, encoding="utf-8")
        (self.artifacts / (stage + ".png")).write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))
        return ET.fromstring(xml)

    def tap(self, label, stage):
        for attempt in range(5):
            hierarchy = self.capture(stage + "-" + str(attempt))
            for node in hierarchy.iter("node"):
                if node.get("text") != label or node.get("enabled") != "true":
                    continue
                bounds = re.fullmatch(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]", node.get("bounds", ""))
                if bounds:
                    left, top, right, bottom = map(int, bounds.groups())
                    self.adb("shell", "input", "tap", str((left + right) // 2), str((top + bottom) // 2))
                    return
            time.sleep(0.5)
        raise RuntimeError("Enabled UI button not found: " + label)

    def forward(self, device_port):
        value = self.adb("forward", "tcp:0", "tcp:" + str(device_port)).strip()
        port = int(value)
        self.forwarded.append(port)
        return port

    def close(self):
        (self.artifacts / "logcat.txt").write_text(self.adb("logcat", "-d", check=False), encoding="utf-8")
        (self.artifacts / "crash-logcat.txt").write_text(self.adb("logcat", "-b", "crash", "-d", check=False), encoding="utf-8")
        for port in self.forwarded:
            self.adb("forward", "--remove", "tcp:" + str(port), check=False)


def rpc(schema, port, method, token=None):
    request = schema.request_type(method)()
    metadata = (("x-auth-token", token),) if token else ()
    with grpc.insecure_channel("127.0.0.1:" + str(port)) as channel:
        raw = channel.unary_unary(method)(codec.encode(request.SerializeToString()), metadata=metadata, timeout=2)
    return schema.response_type(method).FromString(codec.decode(raw))


def bootstrap(schema, port):
    """Follow the observed title-screen order without a prior local login."""
    check = rpc(schema, port, "/api.System/Check")
    term = rpc(schema, port, "/api.Refund/GetTerm")
    # In the client, zero refund dates mean an unbounded active refund period.
    # A future period hides that entry, while shopInvalid=0 closes the unsupported
    # financial shop. Positive shopInvalid would advertise a normal stone shop.
    actual = (term.endDatetime, term.startDatetime, term.shopInvalidStartDatetime)
    if actual != (LOCAL_REFUND_DATE, LOCAL_REFUND_DATE, 0) or term.startDatetime <= time.time() * 1000:
        raise RuntimeError("Anonymous Refund.GetTerm did not disable local refund and financial entries")
    login = rpc(schema, port, "/api.Auth/Login")
    return check, login


def wait_server(schema, port, expected=True, timeout=120):
    deadline = time.monotonic() + timeout
    next_progress = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            rpc(schema, port, "/api.System/Check")
            ready = True
        except grpc.RpcError:
            ready = False
        if ready == expected:
            return
        if time.monotonic() >= next_progress:
            print("Waiting for native server " + ("startup" if expected else "shutdown"), flush=True)
            next_progress = time.monotonic() + 15
        time.sleep(0.5)
    raise RuntimeError("Server did not " + ("start" if expected else "stop") + " before the timeout")


def assert_starter_roster(user):
    if len(user.characters) != 17 or {row.characterId for row in user.characters} != STARTER_CHARACTERS:
        raise RuntimeError("Native starter roster does not contain the 17 unconditional office characters")
    costumes = {row.costumeId for row in user.costumes}
    hairs = {row.hairId for row in user.hairs}
    for row in user.characters:
        if (not row.favoriteCostumeId or row.favoriteCostumeId not in costumes
                or not row.liveCostumeId or row.liveCostumeId not in costumes
                or not row.favoriteHairId or row.favoriteHairId not in hairs
                or not row.liveHairId or row.liveHairId not in hairs):
            raise RuntimeError("Native starter character is missing an owned favorite/live appearance")


def _legacy_projection(user):
    """Remove only the 12 office actors and their unshared owned appearances."""
    projected = type(user)()
    projected.CopyFrom(user)
    kept = [row for row in user.characters if row.characterId in PHOTO_CHARACTERS]
    removed = [row for row in user.characters if row.characterId not in PHOTO_CHARACTERS]
    costume_ids = lambda rows: {key for row in rows for key in (row.favoriteCostumeId, row.liveCostumeId)}
    hair_ids = lambda rows: {key for row in rows for key in (row.favoriteHairId, row.liveHairId)}
    removed_costumes = costume_ids(removed) - costume_ids(kept)
    removed_hairs = hair_ids(removed) - hair_ids(kept)
    for name, remove in (("characters", lambda row: row.characterId not in PHOTO_CHARACTERS),
                         ("costumes", lambda row: row.costumeId in removed_costumes),
                         ("hairs", lambda row: row.hairId in removed_hairs)):
        rows = getattr(projected, name)
        for index in reversed(range(len(rows))):
            if remove(rows[index]):
                del rows[index]
    return projected


def _guard_stopped_emulator(qa):
    if (not qa.command[-1].startswith("emulator-")
            or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1"):
        raise RuntimeError("Private database upgrade QA accepts a disposable emulator only")
    if qa.adb("shell", "pidof", "-s", PACKAGE, check=False).strip():
        raise RuntimeError("Private database upgrade QA requires a force-stopped server process")


def _copy_private_database(qa, directory):
    _guard_stopped_emulator(qa)
    path = Path(directory) / "state.db"
    payload = qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE, binary=True)
    if not payload.startswith(b"SQLite format 3\0"):
        raise RuntimeError("Stopped emulator private database is not SQLite")
    path.write_bytes(payload)
    path.chmod(0o600)
    # A forced process exit may leave committed pages in WAL. Copy it before
    # opening SQLite so the host recovers every page; no SHM copy is needed.
    wal_present = subprocess.run([*qa.command, "shell", "run-as", PACKAGE, "test", "-s", PRIVATE_DATABASE + "-wal"],
                                 capture_output=True, timeout=90)
    if wal_present.returncode not in (0, 1):
        raise RuntimeError("Could not inspect the stopped emulator database WAL")
    if wal_present.returncode == 0:
        wal = qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE + "-wal", binary=True)
        if not wal:
            raise RuntimeError("Nonempty stopped emulator database WAL could not be copied")
        wal_path = path.with_name("state.db-wal")
        wal_path.write_bytes(wal)
        wal_path.chmod(0o600)
    return path


def _checkpoint(db):
    if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
        raise RuntimeError("Synthetic emulator database failed SQLite integrity check")
    if db.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0] != 0:
        raise RuntimeError("Synthetic emulator database WAL could not be checkpointed")


def _preserved_tables(db):
    return {name: db.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall() for name in PRESERVED_TABLES}


def stage_legacy_starter(qa, schema, expected_user):
    """Recreate the old five-idol layout only inside this disposable emulator.

    Private DB/WAL bytes live in a TemporaryDirectory and memory, never QA
    artifacts. All identity, session, settings and other snapshot fields remain.
    """
    with tempfile.TemporaryDirectory(prefix="idoly-native-upgrade-") as directory:
        path = _copy_private_database(qa, directory)
        db = sqlite3.connect(path)
        try:
            _checkpoint(db)
            identity = db.execute("SELECT name FROM profiles").fetchall()
            snapshots = db.execute("SELECT profile,response,schema_sha256 FROM snapshots").fetchall()
            marker = db.execute("SELECT profile,version FROM starter_profiles").fetchall()
            if identity != [("sandbox",)] or len(snapshots) != 1 or marker != [("sandbox", 2)]:
                raise RuntimeError("Legacy upgrade fixture requires the fresh synthetic sandbox only")
            profile, payload, fingerprint = snapshots[0]
            if profile != "sandbox" or fingerprint != schema.fingerprint:
                raise RuntimeError("Legacy upgrade fixture does not match the tested schema")
            user = schema.response_type("/api.User/Get").FromString(payload)
            assert_starter_roster(user)
            if user.SerializeToString(deterministic=True) != expected_user.SerializeToString(deterministic=True):
                raise RuntimeError("Stopped synthetic snapshot differs from the tested RPC state")
            if tuple(user.profile.favoriteCharacterIds) != PHOTO_CHARACTERS:
                raise RuntimeError("Legacy upgrade fixture does not match the five photo idols")
            preserved = _preserved_tables(db)
            legacy = _legacy_projection(user)
            if len(legacy.characters) != 5 or {row.characterId for row in legacy.characters} != set(PHOTO_CHARACTERS):
                raise RuntimeError("Legacy upgrade fixture did not produce exactly five idols")
            db.execute("UPDATE snapshots SET response=? WHERE profile=?", (legacy.SerializeToString(), profile))
            db.execute("DELETE FROM starter_profiles WHERE profile=?", (profile,))
            db.commit()
            if _preserved_tables(db) != preserved:
                raise RuntimeError("Legacy fixture changed preserved synthetic database rows")
            _checkpoint(db)
        finally:
            db.close()
        replacement = path.read_bytes()
        _guard_stopped_emulator(qa)
        # Host SQLite has recovered/checkpointed the complete old WAL. Remove
        # only the stopped target's stale sidecars before replacing its DB.
        qa.adb("shell", "run-as", PACKAGE, "rm", "-f", PRIVATE_DATABASE + "-wal", PRIVATE_DATABASE + "-shm")
        written = subprocess.run([*qa.command, "shell", "run-as", PACKAGE, "dd", "of=" + PRIVATE_DATABASE],
                                 input=replacement, capture_output=True, timeout=90)
        if written.returncode:
            raise RuntimeError("Could not restore the synthetic legacy database to the stopped emulator")
        if qa.adb("exec-out", "run-as", PACKAGE, "cat", PRIVATE_DATABASE, binary=True) != replacement:
            raise RuntimeError("Synthetic legacy database write verification failed")
    return legacy, preserved


def verify_upgrade_database(qa, preserved):
    with tempfile.TemporaryDirectory(prefix="idoly-native-upgrade-verify-") as directory:
        path = _copy_private_database(qa, directory)
        db = sqlite3.connect(path)
        try:
            _checkpoint(db)
            if _preserved_tables(db) != preserved:
                raise RuntimeError("Native starter upgrade changed identity, sessions or settings")
            if db.execute("SELECT profile,version FROM starter_profiles").fetchall() != [("sandbox", 2)]:
                raise RuntimeError("Native starter upgrade did not persist its migration marker")
        finally:
            db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--descriptor-set", type=Path, default=Path("data/protocol/idolypride-6.1.1.pb"))
    parser.add_argument("--artifacts", type=Path, default=Path("data/android-server-qa"))
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", default="emulator-5554")
    parser.add_argument("--startup-timeout", type=float, default=600,
                        help="Seconds allowed for native Python startup, including a cold software-emulator launch")
    args = parser.parse_args()
    if args.startup_timeout <= 0:
        parser.error("--startup-timeout must be positive")
    qa = QA(args.adb, args.serial, args.artifacts)
    result = {"ok": False, "target": "Android emulator", "device_game_client_tested": False}
    try:
        if not args.serial.startswith("emulator-") or qa.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
            raise RuntimeError("This QA driver accepts an emulator only")
        print("Installing the native server APK", flush=True)
        qa.adb("install", "-r", "-g", str(args.apk.resolve()))
        qa.adb("logcat", "-c")
        qa.adb("shell", "am", "force-stop", PACKAGE)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        grpc_port, asset_port = qa.forward(50051), qa.forward(8080)
        schema = Schema.from_descriptor_set(args.descriptor_set)
        print("Starting the server through its native UI", flush=True)
        qa.tap("서버 시작", "01-start")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        print("Native server ready; checking encrypted RPCs and HTTP files", flush=True)
        qa.capture("02-running")
        check, login = bootstrap(schema, grpc_port)
        result.update(anonymous_refund_term=True, refund_term_inactive=True,
                      bootstrap_rpc_order=["System.Check", "Refund.GetTerm", "Auth.Login"])
        if not login.gameAuthToken:
            raise RuntimeError("Local login did not return a session")
        user = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not user.HasField("user") or not user.user.name:
            raise RuntimeError("Local User.Get snapshot is absent")
        assert_starter_roster(user)
        result["starter_roster_complete"] = True
        rpc(schema, grpc_port, "/api.Home/Login", login.gameAuthToken)
        home = rpc(schema, grpc_port, "/api.Home/Enter", login.gameAuthToken)
        if not home.currentMainAreaId:
            raise RuntimeError("Local Home.Enter did not resolve the bundled starting area")
        if not home.HasField("hierarchyNotiInfo") or not home.hierarchyNotiInfo.currentDetailGradeId:
            raise RuntimeError("Local Home.Enter did not resolve the bundled hierarchy grade")
        if home.HasField("homeFishHeavenInfo"):
            raise RuntimeError("Local Home.Enter advertised an inactive fish-heaven event and may suppress LoadingManager.Hide")
        result["home_fish_heaven_absent"] = True
        rpc(schema, grpc_port, "/api.Home/SetReview", login.gameAuthToken)
        changed = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Local gameplay changes were not saved")
        master = rpc(schema, grpc_port, "/api.Master/Get", login.gameAuthToken)
        if not master.masterTag.masterTagPacks:
            raise RuntimeError("Local master archive is absent")
        filename = master.masterTag.masterTagPacks[0].fileName
        from urllib.parse import quote

        request = Request("http://127.0.0.1:" + str(asset_port) + "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-31"})
        with urlopen(request, timeout=5) as response:
            if response.status != 206 or len(response.read()) != 32:
                raise RuntimeError("Local master HTTP byte range failed")
        result.update(system_check=check.keepAliveTimeMilliseconds > 0, local_auth=True, home_rpcs=True,
                      home_hierarchy_reference=True,
                      user_snapshot=True, master_packs=len(master.masterTag.masterTagPacks), asset_range=True)
        qa.tap("서버 중지", "03-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.capture("04-stopped")
        # Stop the whole process, preserving its private DB, then exercise a
        # fresh service instance and the previously issued local session.
        qa.adb("shell", "am", "force-stop", PACKAGE)
        legacy, preserved = stage_legacy_starter(qa, schema, changed)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        print("Restarting the app to verify the native five-to-seventeen starter upgrade", flush=True)
        qa.tap("서버 시작", "05-restart")
        wait_server(schema, grpc_port, timeout=args.startup_timeout)
        restored = rpc(schema, grpc_port, "/api.User/Get", login.gameAuthToken)
        if restored.user.name != user.user.name or not restored.user.isReviewed:
            raise RuntimeError("Restart did not preserve the local profile")
        assert_starter_roster(restored)
        if (_legacy_projection(restored).SerializeToString(deterministic=True)
                != legacy.SerializeToString(deterministic=True)):
            raise RuntimeError("Native starter upgrade changed existing snapshot fields or appearance rows")
        result.update(restart_session_preserved=True, gameplay_change_preserved=True, port_rebound=True)
        result.update(legacy_starter_upgraded=True, upgrade_snapshot_fields_preserved=True)
        qa.capture("06-restarted")
        qa.tap("서버 중지", "07-final-stop")
        wait_server(schema, grpc_port, expected=False, timeout=30)
        qa.adb("shell", "am", "force-stop", PACKAGE)
        verify_upgrade_database(qa, preserved)
        result.update(upgrade_identity_preserved=True, upgrade_sessions_preserved=True, upgrade_settings_preserved=True)
        qa.adb("shell", "am", "start", "-n", ACTIVITY)
        result.update(ok=True, final_stop=True)
    except BaseException as error:
        result["error_type"] = type(error).__name__
        result["error"] = str(error)
        raise
    finally:
        try:
            qa.capture("08-final")
        except Exception:
            pass
        qa.close()
        (args.artifacts / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
