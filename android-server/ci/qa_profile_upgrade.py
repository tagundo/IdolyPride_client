"""Actual native APK update/profile/mission checks on this owned synthetic guest.

No account tokens, protobuf bodies or private databases are exported. UI inputs
are ordinary Android touches derived from fresh accessibility trees.
"""
from pathlib import Path, PurePosixPath
from datetime import datetime, timezone
import argparse
import hashlib
import json
import re
import subprocess
from zipfile import ZipFile

import grpc
import qa_emulator as q
from qa_target import verify_disposable_target
from idoly_local.tutorial_qa import _assert_enhancement_missions

PACKAGE = q.PACKAGE
MISSION = "ms-normal-card_level_achievement"


def digest(value):
    return hashlib.sha256(value.SerializeToString(deterministic=True)).hexdigest()


def require(value, reason):
    if not value:
        raise RuntimeError(reason)


def clone(value):
    result = type(value)()
    result.CopyFrom(value)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--adb', default='adb')
    parser.add_argument('--serial', default='127.0.0.1:6520')
    parser.add_argument('--data-root', type=Path, default=Path('data'))
    parser.add_argument('--baseline-source', required=True)
    parser.add_argument('--baseline-apk-sha256', required=True)
    parser.add_argument('--startup-timeout', type=float, default=600)
    parser.add_argument('--new-apk', type=Path, required=True)
    parser.add_argument('--new-source', required=True)
    parser.add_argument('--new-apk-sha256', required=True)
    parser.add_argument('--new-payload-sha256', required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    args = parser.parse_args()
    for value in (args.baseline_source, args.new_source):
        if not re.fullmatch(r'[0-9a-f]{40}', value):
            parser.error('Source commits must be full lowercase SHA-1 values')
    for value in (args.baseline_apk_sha256, args.new_apk_sha256, args.new_payload_sha256):
        if not re.fullmatch(r'[0-9a-f]{64}', value):
            parser.error('Expected digests must be full lowercase SHA-256 values')
    if args.startup_timeout <= 0:
        parser.error('--startup-timeout must be positive')
    qa = q.QA(args.adb, args.serial, args.artifacts)
    result = {'schema': 1, 'ok': False, 'compiled_source_commit': args.new_source,
              'apk_sha256': args.new_apk_sha256, 'payload_sha256': args.new_payload_sha256,
              'previous_source_commit': args.baseline_source,
              'previous_apk_sha256': args.baseline_apk_sha256,
              'private_state_exported': False, 'game_client_gameplay_tested': False,
              'diagnostics_collector_tested': False, 'final_server_stopped': False,
              'qa_script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    started = False
    verified_target = False
    try:
        result['target_evidence'] = verify_disposable_target(qa.adb, args.serial)
        require(result['target_evidence']['kind'] == 'cuttlefish_arm64_only',
                'This upgrade proof requires the observed ARM64-only Cuttlefish guest')
        verified_target = True
        def installed_hash():
            paths = qa.adb('shell', 'pm', 'path', PACKAGE).splitlines()
            require(len(paths) == 1 and paths[0].startswith('package:'), 'Installed server APK path is ambiguous')
            path = paths[0][len('package:'):]
            require(re.fullmatch(r'/data/app/[A-Za-z0-9_./=+~\-]+/base\.apk', path) is not None,
                    'Installed server APK path is outside its package location')
            output = qa.adb('shell', 'sha256sum', path).split()
            require(output and re.fullmatch(r'[0-9a-f]{64}', output[0]) is not None,
                    'Installed server APK hash was not available')
            return output[0]
        result['baseline_installed_apk_sha256'] = installed_hash()
        require(result['baseline_installed_apk_sha256'] == args.baseline_apk_sha256,
                'Installed baseline APK hash mismatch')
        require(hashlib.sha256(args.new_apk.read_bytes()).hexdigest() == args.new_apk_sha256,
                'Updated APK hash mismatch')
        with ZipFile(args.new_apk) as outer:
            assets = [name for name in outer.namelist() if name.endswith('ServerData.zip')]
            require(len(assets) == 1, 'Updated APK payload identity is ambiguous')
            with outer.open(assets[0]) as stream:
                require(hashlib.file_digest(stream, 'sha256').hexdigest() == args.new_payload_sha256,
                        'Updated embedded payload hash mismatch')
            with outer.open(assets[0]) as stream, ZipFile(stream) as payload:
                for name in payload.namelist():
                    if name.startswith(('data/protocol/', 'data/master-json/')) and not name.endswith('/'):
                        relative = PurePosixPath(name)
                        require(not relative.is_absolute() and '..' not in relative.parts,
                                'Updated public payload has an unsafe input path')
                        original = args.data_root.joinpath(*relative.parts[1:])
                        require(original.is_file() and payload.read(name) == original.read_bytes(),
                                'Updated protocol/master differs from baseline QA inputs')
        schema = q.Schema.from_descriptor_set(args.data_root / 'protocol/idolypride-6.1.1.pb')
        master = args.data_root / 'master-json'
        q.bind_starter_contract(qa, schema, master)
        port = qa.forward(50051)
        def rpc(path, token=None, **fields):
            return q.rpc(schema, port, path, token, schema.request_type(path)(**fields))
        def user(token):
            return rpc('/api.User/Get', token)
        def start(stage):
            nonlocal started
            qa.adb('shell', 'am', 'start', '-n', q.ACTIVITY)
            qa.tap('서버 시작', stage)
            q.wait_server(schema, port, timeout=args.startup_timeout)
            started = True
        def stop(stage):
            nonlocal started
            qa.tap('서버 중지', stage)
            q.wait_server(schema, port, expected=False, timeout=30)
            qa.adb('shell', 'am', 'force-stop', PACKAGE)
            started = False
        def rejected(path, token, **fields):
            try:
                rpc(path, token, **fields)
            except grpc.RpcError as error:
                require(error.code() == grpc.StatusCode.INVALID_ARGUMENT,
                        'Wrong validation status for ' + path)
            else:
                raise RuntimeError('Expected input rejection for ' + path)
        start('01-old-apk-start')
        _, login = q.bootstrap(schema, port)
        token = login.gameAuthToken
        before = user(token)
        favorites = list(before.profile.favoriteCharacterIds)
        require(len(favorites) == 5 and len(set(favorites)) == 5,
                'Needs the existing five distinct starter favorites')
        rejected('/api.Profile/UpdateFavoriteCharacters', token, favoriteCharacterIds=favorites)
        require(digest(user(token)) == digest(before), 'Old rejected favorites changed the snapshot')
        result['old_five_favorite_bug_reproduced'] = True
        stop('02-old-apk-stop')
        # Install-r keeps this actual tested native profile/session. Do not clear.
        qa.adb('install', '-r', '-g', str(args.new_apk.resolve()))
        result['installed_apk_sha256'] = installed_hash()
        require(result['installed_apk_sha256'] == args.new_apk_sha256, 'Installed updated APK hash mismatch')
        package_info = qa.adb('shell', 'dumpsys', 'package', PACKAGE)
        require(re.search(r'\bprimaryCpuAbi=arm64-v8a\b', package_info) is not None,
                'Installed updated APK does not have the production ARM64 ABI')
        result['installed_primary_cpu_abi'] = 'arm64-v8a'
        start('03-updated-apk-start')
        require(digest(user(token)) == digest(before), 'Install-r changed snapshot or lost original session')
        result['install_r_snapshot_session_preserved'] = True
        profile = rpc('/api.Profile/Top', token)
        detail_ids = {row['id'] for row in json.loads((master / 'HierarchyDetailGrade.json').read_text())}
        require(profile.hierarchyCurrentDetailGradeId in detail_ids and profile.hierarchyCurrentRank == 0
                and not profile.friendProfiles, 'Profile.Top returned an unsupported local header')
        require(digest(user(token)) == digest(before), 'Read-only Profile.Top changed snapshot')
        result['profile_top_readonly'] = True
        response = rpc('/api.Profile/UpdateName', token, name='NativeQA')
        after = user(token)
        expected = clone(before)
        expected.user.name = 'NativeQA'
        require(digest(after) == digest(expected) and response.commonResponse.updatedData.user == after.user,
                'Name update changed fields beyond the user name')
        rejected('/api.Profile/UpdateName', token, name='TooLongNativeName')
        require(digest(user(token)) == digest(after), 'Rejected name changed snapshot')
        result['profile_name_delta_and_rejection'] = True
        response = rpc('/api.Profile/UpdateMessage', token, message='Native QA\n보존')
        expected = clone(after)
        expected.profile.message = 'Native QA\n보존'
        after = user(token)
        require(digest(after) == digest(expected) and response.commonResponse.updatedData.profile == after.profile,
                'Message update changed fields beyond the profile message')
        rejected('/api.Profile/UpdateMessage', token, message='a' * 61)
        require(digest(user(token)) == digest(after), 'Rejected message changed snapshot')
        result['profile_message_delta_and_rejection'] = True
        for selected in (favorites, list(reversed(favorites)), [], favorites):
            expected = clone(after)
            del expected.profile.favoriteCharacterIds[:]
            expected.profile.favoriteCharacterIds.extend(selected)
            response = rpc('/api.Profile/UpdateFavoriteCharacters', token, favoriteCharacterIds=selected)
            after = user(token)
            require(digest(after) == digest(expected)
                    and response.commonResponse.updatedData.profile == after.profile,
                    'Favorite selection changed unrelated fields or order')
        retry_before = digest(after)
        rpc('/api.Profile/UpdateFavoriteCharacters', token, favoriteCharacterIds=favorites)
        require(digest(user(token)) == retry_before, 'Identical favorite retry changed snapshot')
        rejected('/api.Profile/UpdateFavoriteCharacters', token, favoriteCharacterIds=[favorites[0], favorites[0]])
        require(digest(user(token)) == retry_before, 'Rejected duplicate favorites changed snapshot')
        result['five_favorites_order_clear_retry_and_rejection'] = True
        missions = rpc('/api.Mission/List', token)
        saved = [row for row in after.missions if row.missionId == MISSION]
        require(len(saved) == 1 and len(missions.userMissions) == 1
                and missions.userMissions[0] == saved[0], 'Mission.List does not match the saved supported subset')
        require(digest(user(token)) == digest(after), 'Read-only Mission.List changed snapshot')
        result['mission_list_saved_subset_readonly'] = True
        card = max((row for row in after.cards if not row.supported), key=lambda row: row.level)
        require(sum(row.cardId == card.cardId for row in after.cards) == 1, 'Owned target card is ambiguous')
        before_items = [row for row in after.items if row.itemId == 'item-card_enhance' and not row.expiredTime]
        require(len(before_items) == 1, 'Permanent enhancement item is ambiguous')
        current_level = card.level
        target_level = current_level + 1
        levels = {row['level']: int(row['requiredExp']) for row in json.loads((master / 'CardLevel.json').read_text())}
        require(target_level in levels, 'No bounded next level in actual CardLevel master')
        cost = levels[target_level] - card.totalExp
        pieces = lambda snapshot: sum(row.amount for row in snapshot.items
                                      if row.itemId == 'item-card_enhance' and not row.expiredTime)
        require(cost > 0 and pieces(after) >= cost, 'Synthetic profile lacks the computed next-level cost')
        response = rpc('/api.Card/Enhance', token, cardId=card.cardId, level=target_level)
        enhanced = user(token)
        require(pieces(enhanced) == pieces(after) - cost, 'Native enhancement consumption differs from master')
        changed_cards = [row for row in enhanced.cards if row.cardId == card.cardId]
        changed_items = [row for row in enhanced.items if row.itemId == 'item-card_enhance' and not row.expiredTime]
        require(len(changed_cards) == len(changed_items) == 1, 'Enhanced card or item identity became ambiguous')
        changed_card, changed_item = changed_cards[0], changed_items[0]
        require(changed_card.level == changed_card.baseLevel == target_level
                and changed_card.totalExp == levels[target_level]
                and changed_card.obtainedTime == card.obtainedTime,
                'Native enhancement did not preserve the bounded target identity/level')
        row_bytes = lambda rows: [row.SerializeToString(deterministic=True) for row in rows]
        require(row_bytes(row for row in after.cards if row.cardId != card.cardId)
                == row_bytes(row for row in enhanced.cards if row.cardId != card.cardId),
                'Enhancement changed unrelated cards or their order')
        other_items = lambda snapshot: (row for row in snapshot.items
            if row.itemId != 'item-card_enhance' or row.expiredTime)
        require(row_bytes(other_items(after)) == row_bytes(other_items(enhanced)),
                'Enhancement changed unrelated or expired item rows')
        expected_item = clone(before_items[0])
        expected_item.amount -= cost
        require(changed_item == expected_item, 'Enhancement changed other target item fields')
        require(len(response.commonResponse.updatedData.cards) == 1
                and response.commonResponse.updatedData.cards[0] == changed_card
                and len(response.commonResponse.updatedData.items) == 1
                and response.commonResponse.updatedData.items[0] == changed_item,
                'Enhancement response card/item delta differs from persisted rows')
        unrelated_before, unrelated_after = clone(after), clone(enhanced)
        for field in ('cards', 'items', 'missions'):
            unrelated_before.ClearField(field)
            unrelated_after.ClearField(field)
        require(digest(unrelated_before) == digest(unrelated_after), 'Enhancement changed unrelated state')
        _assert_enhancement_missions(after, enhanced, response, master, card.cardId)
        delta = response.commonResponse.updatedData.missions
        expected_delta = target_level > saved[0].progress
        require(len(delta) == int(expected_delta), 'Enhancement emitted the wrong mission delta count')
        if expected_delta:
            require(delta[0].missionId == MISSION and delta[0].progress == target_level,
                    'Enhancement omitted the bounded high-water progress')
        retry = rpc('/api.Card/Enhance', token, cardId=card.cardId, level=current_level + 1)
        require(not retry.commonResponse.updatedData.missions
                and digest(user(token)) == digest(enhanced), 'Same-level enhancement retry changed state')
        refreshed = rpc('/api.Mission/List', token)
        persisted_mission = next(row for row in enhanced.missions if row.missionId == MISSION)
        require(len(refreshed.userMissions) == 1 and refreshed.userMissions[0] == persisted_mission
                and digest(user(token)) == digest(enhanced), 'Mission.List did not reflect the new saved progress')
        result['card_level_mission_delta_verified'] = True
        result['mission_progress_increased'] = expected_delta
        result['mission_response_delta_count'] = len(delta)
        result['enhancement_cost'] = cost
        result['mission_level_before'] = current_level
        result['mission_level_after'] = current_level + 1
        stop('04-updated-state-stop')
        start('05-updated-state-restart')
        require(digest(user(token)) == digest(enhanced), 'Native restart lost profile/mission state or original session')
        result['native_restart_snapshot_session_preserved'] = True
        stop('06-final-stop')
        require(not qa.adb('shell', 'pidof', '-s', PACKAGE, check=False).strip(), 'Native APK did not stop')
        result.update(ok=True, final_server_stopped=True, snapshot_sha256=digest(enhanced))
    except BaseException as error:
        result['error_type'] = type(error).__name__
        result['error'] = str(error) if isinstance(error, RuntimeError) else 'Probe operation failed'
        raise
    finally:
        result['finished_utc'] = datetime.now(timezone.utc).isoformat()
        # Do not silently change the app on failure; leave its actual state for
        # diagnosis. The owner may stop it through the normal UI afterward.
        result['server_started_when_finishing'] = started
        if verified_target:
            qa.close()
        (args.artifacts / 'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
