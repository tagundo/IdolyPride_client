#!/usr/bin/env python3
"""Private frozen server engine controlled by the native app over JSON lines."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import signal
import socket
import sys
import threading
import time

from payload import install_payload

_OUTPUT_LOCK = threading.Lock()


def emit(event: str, **values):
    with _OUTPUT_LOCK:
        print(json.dumps({"event": event, **values}, ensure_ascii=False), flush=True)


class Controller:
    def __init__(self, data_dir, server_data, profile="sandbox", emit_event=emit):
        self.data_dir, self.server_data = Path(data_dir), Path(server_data)
        self.profile, self.emit = profile, emit_event
        self.lock = threading.RLock()
        self.runtime = self.worker = None
        self.cancelled = False
        self.closed = False

    def log(self, message):
        self.emit("log", message=str(message))

    def status(self):
        with self.lock:
            runtime = self.runtime
            starting = bool(self.worker and self.worker.is_alive() and runtime is None and not self.cancelled)
            status = runtime.status() if runtime else {
                "running": False, "profile": self.profile,
                "grpc_address": "127.0.0.1:50051", "asset_url": "http://127.0.0.1:8080"}
            status = {key: value for key, value in status.items() if key != "logs"}
            status["starting"] = starting
            status["can_stop"] = runtime is not None or starting
        self.emit("status", status=status)
        return status

    def start(self):
        with self.lock:
            if self.closed or self.runtime or (self.worker and self.worker.is_alive()):
                return self.status()
            self.cancelled = False
            self.worker = threading.Thread(target=self._start, name="local-server-start", daemon=False)
            self.worker.start()
        self.status()

    def _start(self):
        runtime = None
        try:
            self.log("서버 데이터를 준비하고 있습니다.")
            install_payload(self.server_data, self.data_dir, self.log)
            from idoly_local import app_runtime
            with self.lock:
                if self.cancelled or self.closed:
                    return
            runtime = app_runtime.start(self.data_dir, profile=self.profile, log_callback=self.log)
            with self.lock:
                self.runtime = runtime
                cancelled = self.cancelled or self.closed
            if cancelled:
                self.stop()
            else:
                self.log("로컬 서버가 시작되었습니다.")
        except Exception as error:
            if runtime is not None:
                with self.lock:
                    self.runtime = runtime
                self.stop()
            self.log(f"서버 시작 실패: {type(error).__name__}: {error}")
            self.emit("error", message="서버를 시작하지 못했습니다. 데이터와 포트 사용 상태를 확인해 주세요.")
        finally:
            # This worker is about to finish; avoid reporting a stale starting state.
            with self.lock:
                self.worker = None
            self.status()

    def stop(self):
        with self.lock:
            self.cancelled = True
            runtime = self.runtime
        if runtime is not None:
            try:
                runtime.stop()
            except Exception as error:
                self.log(f"서버 중지 실패: {type(error).__name__}: {error}")
                self.emit("error", message="서버를 완전히 중지하지 못했습니다. 중지를 다시 눌러 주세요.")
            else:
                with self.lock:
                    if self.runtime is runtime:
                        self.runtime = None
                self.log("로컬 서버가 중지되었습니다.")
        return self.status()

    def close(self):
        with self.lock:
            self.closed = True
            worker = self.worker
        self.stop()
        if worker and worker is not threading.current_thread():
            worker.join(timeout=20)
        self.stop()


def _rpc(address, schema, method, request=None, token=None):
    """Exercise the frozen pure-Python HTTP/2 stack without importing grpcio."""
    from h2.config import H2Configuration
    from h2.connection import H2Connection
    from h2.events import DataReceived, StreamEnded, TrailersReceived
    from idoly_local import codec

    if request is None:
        request = schema.request_type(method)()
    payload = codec.encode(request.SerializeToString())
    host, port = address.rsplit(":", 1)
    client = H2Connection(H2Configuration(client_side=True, header_encoding="utf-8"))
    client.initiate_connection()
    headers = [(":method", "POST"), (":scheme", "http"), (":authority", address),
        (":path", method), ("content-type", "application/grpc+proto"), ("te", "trailers")]
    if token is not None:
        headers.append(("x-auth-token", token))
    client.send_headers(1, headers)
    client.send_data(1, b"\0" + len(payload).to_bytes(4, "big") + payload, end_stream=True)
    body, status, ended = bytearray(), None, False
    with socket.create_connection((host, int(port)), timeout=5) as stream:
        stream.sendall(client.data_to_send())
        while not ended:
            data = stream.recv(65535)
            if not data:
                raise RuntimeError("HTTP/2 RPC ended before its trailers")
            for event in client.receive_data(data):
                if isinstance(event, DataReceived):
                    body.extend(event.data)
                    client.acknowledge_received_data(event.flow_controlled_length, event.stream_id)
                elif isinstance(event, TrailersReceived):
                    status = dict(event.headers).get("grpc-status")
                elif isinstance(event, StreamEnded):
                    ended = True
            pending = client.data_to_send()
            if pending:
                stream.sendall(pending)
    if status != "0" or len(body) < 5 or body[0] != 0 or int.from_bytes(body[1:5], "big") != len(body) - 5:
        raise RuntimeError("Local RPC returned an invalid gRPC response: " + method)
    return schema.response_type(method).FromString(codec.decode(bytes(body[5:])))


def _home_hierarchy_reference(home, data_dir):
    grade_id = home.hierarchyNotiInfo.currentDetailGradeId
    if not grade_id:
        return False
    master_dir = Path(data_dir) / "master-json"
    details = json.loads((master_dir / "HierarchyDetailGrade.json").read_text())
    grades = json.loads((master_dir / "HierarchyGrade.json").read_text())
    matches = [row for row in details if row.get("id") == grade_id]
    if len(matches) != 1:
        return False
    parent_id = matches[0].get("hierarchyGradeId")
    return bool(parent_id) and sum(row.get("id") == parent_id for row in grades) == 1


def _home_positions_distinct(user):
    positions = list(user.homePositions)
    assigned = {row.characterId for row in positions}
    owned = {row.characterId for row in user.characters}
    return (len(positions) == 4 and {row.homePositionType for row in positions} == {1, 2, 3, 4}
            and len(assigned) == 4 and assigned.issubset(owned)
            and all(not row.isCharacterRandom and not row.isCostumeRandom for row in positions)
            and next(row.characterId for row in positions if row.homePositionType == 1) == "char-ktn")


def _quest_catalog_reference(top, main, data_dir):
    """Check encrypted responses against the bundled public table references."""
    if ([group.SerializeToString() for group in top.mainAreaGroups]
            != [group.SerializeToString() for group in main.areaGroups]):
        raise RuntimeError("Quest.Top and Quest.ListMain returned different main area groups")
    if (not top.HasField("pvpInfo") or top.pvpInfo.HasField("latestPvpSeason")
            or not top.HasField("hierarchyNotiInfo") or not _home_hierarchy_reference(top, data_dir)):
        raise RuntimeError("Quest.Top omitted required local PvP/hierarchy references")
    master_dir = Path(data_dir) / "master-json"

    def rows(name):
        values = json.loads((master_dir / (name + ".json")).read_text())
        identities = [row.get("id") for row in values]
        if not values or any(not isinstance(key, str) or not key for key in identities) or len(set(identities)) != len(values):
            raise RuntimeError("Quest smoke check needs unique bundled " + name + " identities")
        return {row["id"]: row for row in values}

    groups, areas, quests = rows("AreaGroup"), rows("Area"), rows("Quest")
    main_ids = {key for key, row in areas.items() if row.get("type") == 1}
    ordered_groups = sorted(groups.values(), key=lambda row: (int(row.get("order", 0)), row["id"]))
    expected_groups = []
    for group in ordered_groups:
        area_ids = group.get("areaIds")
        if not isinstance(area_ids, list) or not area_ids or any(key not in areas for key in area_ids):
            raise RuntimeError("Bundled AreaGroup references an absent area")
        if any(key in main_ids for key in area_ids):
            expected_groups.append(group)
    if [group.areaGroupId for group in top.mainAreaGroups] != [group["id"] for group in expected_groups]:
        raise RuntimeError("Quest group identities/order do not match the bundled AreaGroup catalog")
    seen_areas, seen_quests = set(), set()
    for output_group, group in zip(top.mainAreaGroups, expected_groups):
        if [area.areaId for area in output_group.areas] != group["areaIds"]:
            raise RuntimeError("Quest area identities/order do not match bundled AreaGroup references")
        for output_area in output_group.areas:
            area_id = output_area.areaId
            area = areas[area_id]
            if (area_id not in main_ids or area_id in seen_areas
                    or area.get("areaGroupId") != group["id"]):
                raise RuntimeError("Quest area does not belong to its bundled main group")
            seen_areas.add(area_id)
            quest_ids = area.get("questIds")
            if not quest_ids or [quest.questId for quest in output_area.quests] != quest_ids:
                raise RuntimeError("Quest identities/order do not match bundled Area references")
            for output_quest in output_area.quests:
                quest_id = output_quest.questId
                if (quest_id in seen_quests or quest_id not in quests
                        or quests[quest_id].get("areaId") != area_id):
                    raise RuntimeError("Quest does not belong to its bundled main area")
                seen_quests.add(quest_id)
    if not main_ids or seen_areas != main_ids or not seen_quests:
        raise RuntimeError("Quest responses did not cover the bundled main catalog")
    first_area = top.mainAreaGroups[0].areas[0]
    first_quest = first_area.quests[0]
    if not first_area.unlocked or not first_quest.isPlayable or first_quest.cleared:
        raise RuntimeError("Fresh starter's first main quest must be playable and uncleared")
    return first_quest.questId


def smoke(data_dir, server_data, report_path):
    from http.client import HTTPConnection
    from urllib.parse import quote, urlsplit
    from idoly_local import app_runtime
    from idoly_local.schema import Schema
    from idoly_local.state import State

    install_payload(server_data, data_dir)
    runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
    report = {"frozen_runtime": bool(getattr(sys, "frozen", False)), "server_started": False,
              "encrypted_system_check": False, "anonymous_refund_term": False, "anonymous_public_text": False,
              "local_auth": False, "home_login": False, "home_enter": False,
              "home_hierarchy_reference": False, "home_fish_heaven_absent": False,
              "starter_roster_complete": False, "home_positions_distinct": False,
              "quest_top_list_main": False, "quest_catalog_readonly": False,
              "settings_persisted": False, "profile_persisted": False,
              "asset_range": False, "server_stopped": False, "game_client_tested": False}
    try:
        status = runtime.status()
        report["server_started"] = bool(status["running"])
        schema = Schema.from_descriptor_set(Path(data_dir) / "protocol/idolypride-6.1.1.pb")
        address = status["grpc_address"]
        check = _rpc(address, schema, "/api.System/Check")
        report["encrypted_system_check"] = check.keepAliveTimeMilliseconds > 0
        refund = _rpc(address, schema, "/api.Refund/GetTerm")
        report["anonymous_refund_term"] = (
            refund.endDatetime, refund.startDatetime, refund.shopInvalidStartDatetime
        ) == (4102444800000, 4102444800000, 0)
        if not report["anonymous_refund_term"]:
            raise RuntimeError("Local refund period must be inactive and the unsupported financial shop closed")
        # These title-screen calls must succeed before any local Auth.Login.
        rule_request = schema.request_type("/api.Master/Rule")(ruleType=1)
        rule = _rpc(address, schema, "/api.Master/Rule", rule_request)
        help_request = schema.request_type("/api.Master/GetHelpCategory")(helpType=1)
        help_response = _rpc(address, schema, "/api.Master/GetHelpCategory", help_request)
        report["anonymous_public_text"] = bool(rule.text and help_response.helpCategories)
        login = _rpc(address, schema, "/api.Auth/Login")
        token = login.gameAuthToken
        if not token:
            raise RuntimeError("Local Auth.Login did not issue a local session")
        report["local_auth"] = True
        before = _rpc(address, schema, "/api.User/Get", token=token)
        # HomeOfficeActors selects from the master's unlocked normal roster,
        # then requires a matching UserCharacter with owned favorite/live
        # appearances. Checking the actual RPC catches the former five-row
        # seed even if initialization and Home.Enter themselves succeed.
        required_characters = {"char-ai", "char-aoi", "char-chs", "char-hrk", "char-kkr", "char-ktn",
            "char-mei", "char-ngs", "char-rei", "char-rio", "char-rui", "char-ski", "char-skr",
            "char-smr", "char-suz", "char-szk", "char-yu"}
        characters = {row.characterId: row for row in before.characters}
        costumes = {row.costumeId for row in before.costumes if row.costumeId}
        hairs = {row.hairId for row in before.hairs if row.hairId}
        report["starter_roster_complete"] = required_characters.issubset(characters) and all(
            characters[key].favoriteCostumeId in costumes and characters[key].liveCostumeId in costumes
            and characters[key].favoriteHairId in hairs and characters[key].liveHairId in hairs
            for key in required_characters)
        if not report["starter_roster_complete"]:
            raise RuntimeError("User.Get must contain all 17 starter characters and their owned favorite/live appearances")
        report["home_positions_distinct"] = _home_positions_distinct(before)
        if not report["home_positions_distinct"]:
            raise RuntimeError("User.Get must assign four distinct owned home characters and preserve Home1 char-ktn")
        saved_before_quests = State(Path(data_dir) / "state.db").snapshot("sandbox")
        top = _rpc(address, schema, "/api.Quest/Top", token=token)
        main = _rpc(address, schema, "/api.Quest/ListMain", token=token)
        report["quest_catalog_first_quest"] = _quest_catalog_reference(top, main, data_dir)
        report["quest_top_list_main"] = True
        after_quests = _rpc(address, schema, "/api.User/Get", token=token)
        report["quest_catalog_readonly"] = (
            State(Path(data_dir) / "state.db").snapshot("sandbox") == saved_before_quests
            and after_quests.SerializeToString() == before.SerializeToString())
        if not report["quest_catalog_readonly"]:
            raise RuntimeError("Read-only Quest.Top/ListMain changed the local snapshot")
        home_request = schema.request_type("/api.Home/Login")()
        home_request.settingInfo.soundBgm = 37
        home_request.settingInfo.soundEffect = 29
        home_request.settingInfo.soundVoice = 61
        home_request.settingInfo.frameRate = 30
        home_request.settingInfo.nightMode = True
        expected_settings = home_request.settingInfo.SerializeToString()
        home_login = _rpc(address, schema, "/api.Home/Login", home_request, token)
        report["home_login"] = home_login.HasField("commonResponse")
        home = _rpc(address, schema, "/api.Home/Enter", token=token)
        report["home_enter"] = bool(home.currentMainAreaId and home.HasField("lessonProgress"))
        report["home_fish_heaven_absent"] = not home.HasField("homeFishHeavenInfo")
        if not report["home_fish_heaven_absent"]:
            raise RuntimeError("Home.Enter advertised an inactive fish-heaven event and may suppress LoadingManager.Hide")
        report["home_hierarchy_reference"] = _home_hierarchy_reference(home, data_dir)
        if not report["home_hierarchy_reference"]:
            raise RuntimeError("Home.Enter hierarchy grade does not resolve through the bundled master tables")
        _rpc(address, schema, "/api.Home/SetReview", token=token)
        changed = _rpc(address, schema, "/api.User/Get", token=token)
        if changed.user.name != before.user.name or not changed.user.isReviewed or changed.user.lastLoginTime <= 0:
            raise RuntimeError("Home calls did not preserve and update the local user")
        saved_user = changed.SerializeToString()
        tag = json.loads((Path(data_dir) / "original-master/master-tag.json").read_text())
        filename = tag["masterTagPacks"][0]["fileName"]
        expected = (Path(data_dir) / "original-master/assets/master" / filename).read_bytes()[:64]
        url = urlsplit(status["asset_url"])
        connection = HTTPConnection(url.hostname, url.port, timeout=5)
        try:
            connection.request("GET", "/master/" + quote(filename, safe=""), headers={"Range": "bytes=0-63"})
            result = connection.getresponse()
            report["asset_range"] = result.status == 206 and result.read() == expected
        finally:
            connection.close()
        runtime.stop()
        # Reopen both listeners and SQLite state, then reuse the previous local
        # session to prove mutations survived a fresh runtime instance.
        runtime = app_runtime.start(data_dir, grpc_port=0, asset_port=0)
        restored = _rpc(runtime.status()["grpc_address"], schema, "/api.User/Get", token=token)
        report["profile_persisted"] = restored.SerializeToString() == saved_user
        settings = State(Path(data_dir) / "state.db").settings("sandbox")
        report["settings_persisted"] = settings == (expected_settings, schema.fingerprint)
    finally:
        runtime.stop()
        report["server_stopped"] = runtime.status()["running"] is False
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    required = ("server_started", "encrypted_system_check", "anonymous_refund_term", "anonymous_public_text", "local_auth", "home_login",
                "home_enter", "home_hierarchy_reference", "home_fish_heaven_absent", "starter_roster_complete", "home_positions_distinct",
                "quest_top_list_main", "quest_catalog_readonly", "settings_persisted", "profile_persisted", "asset_range", "server_stopped")
    if not all(report[key] for key in required):
        raise RuntimeError("Bundled engine smoke check failed")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--server-data", required=True, type=Path)
    parser.add_argument("--json-control", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.smoke:
        if args.report is None:
            parser.error("--smoke requires --report")
        smoke(args.data_dir, args.server_data, args.report)
        return 0
    controller = Controller(args.data_dir, args.server_data)

    def stop_signal(_signum, _frame):
        controller.close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, stop_signal)
    signal.signal(signal.SIGINT, stop_signal)
    controller.status()
    try:
        for line in sys.stdin:
            try:
                command = json.loads(line)
            except (ValueError, TypeError):
                emit("error", message="앱 제어 요청을 읽지 못했습니다.")
                continue
            action = command.get("action") if isinstance(command, dict) else None
            if action == "start":
                controller.start()
            elif action == "stop":
                controller.stop()
            elif action == "status":
                controller.status()
            elif action == "quit":
                break
            else:
                emit("error", message="지원하지 않는 앱 제어 요청입니다.")
    finally:
        controller.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
