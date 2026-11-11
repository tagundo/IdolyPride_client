"""Strict trusted adaptation of the byte-immutable v0.3.1 draft uploader."""
import hashlib
import importlib.util
import json
from pathlib import Path
import re
from unittest.mock import Mock

import pytest
from tools import reviewed_draft_adapter as adapter

REPO = Path(__file__).parents[1]
IDENTITY = ('tagundo/IdolyPride_client', 123, 'local-server-v0.3.2', 'a' * 40, 456)
NAMES = {'android': 'android-server-build-and-available-evidence-v0.3.2',
         'macos': 'macos-server-candidate-and-native-evidence-v0.3.2'}


def bind(path, identity=IDENTITY):
    return adapter.bind(identity=identity, pin_path=path,
                        payload_name='IdolyPride-ServerData-v0.3.2.zip', artifact_names=NAMES)


def pins(engine):
    row = {'bytes': 1, 'sha256': engine.sha(b'x')}
    return {**dict(zip(('repo', 'release_id', 'tag', 'source', 'run_id'), IDENTITY)), 'approved': True,
            'assets': {name: dict(row) for name in engine.ASSETS}, 'body': dict(row), 'proof': dict(row),
            'artifacts': {key: {**row, 'id': i, 'name': NAMES[key]}
                          for i, key in enumerate(('android', 'macos'), 1)}}


@pytest.fixture
def engine(tmp_path):
    path = tmp_path / 'pins.json'; result = bind(path)
    path.write_text(json.dumps(pins(result)))
    return result


def value(p, assets=None):
    return {'id': p['release_id'], 'tag_name': p['tag'], 'target_commitish': p['source'],
            'draft': True, 'prerelease': True, 'body': 'x', 'assets': list((assets or {}).values())}


def test_old_reviewed_source_and_old_release_pins_remain_byte_immutable():
    assert hashlib.sha256(adapter.ENGINE_PATH.read_bytes()).hexdigest() == adapter.ENGINE_SHA256
    assert hashlib.sha256((REPO / 'tools/reviewed-drafts/local-server-v0.3.1.json').read_bytes()).hexdigest() == \
        'fb8d69e6e969c8c668b6f1b714a3a77710e42034ff47f21da966a53659b2ad66'


def test_tampered_legacy_code_is_refused_before_execution(monkeypatch, tmp_path):
    marker = tmp_path / 'executed'
    source = tmp_path / 'engine.py'; source.write_text(f'open({str(marker)!r},"w").write("unsafe")')
    monkeypatch.setattr(adapter, 'ENGINE_PATH', source)
    with pytest.raises(RuntimeError, match='source changed'): bind(tmp_path / 'pins.json')
    assert not marker.exists()


def test_new_binding_is_isolated_and_keeps_v31_globals_unchanged(tmp_path):
    spec = importlib.util.spec_from_file_location('old', adapter.ENGINE_PATH)
    old = importlib.util.module_from_spec(spec); spec.loader.exec_module(old)
    current = bind(tmp_path / 'pins.json')
    assert current is not old and current.PAYLOAD == 'IdolyPride-ServerData-v0.3.2.zip'
    assert current.PAYLOAD in current.ASSETS and old.PAYLOAD not in current.ASSETS
    assert old.PAYLOAD == 'IdolyPride-ServerData-v0.3.1.zip' and old.IDENTITY[1] == 441044576


def test_unapproved_pending_wrapper_refuses_before_any_api(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(REPO / 'tools'))
    spec = importlib.util.spec_from_file_location('v032', REPO / 'tools/stage_reviewed_server_v032_draft.py')
    wrapper = importlib.util.module_from_spec(spec); spec.loader.exec_module(wrapper)
    pending = tmp_path / 'pending.json'; pending.write_text(json.dumps({'approved': False}))
    monkeypatch.setattr(wrapper, 'PIN_PATH', pending)
    current = wrapper.configured_engine(); monkeypatch.setattr(current, 'api', Mock())
    with pytest.raises(RuntimeError, match='not approved'): current.main()
    current.api.assert_not_called()


@pytest.mark.parametrize('identity', [(IDENTITY[0], 0, IDENTITY[2], IDENTITY[3], IDENTITY[4]),
                                    (IDENTITY[0], IDENTITY[1], IDENTITY[2], None, IDENTITY[4]),
                                    (IDENTITY[0], IDENTITY[1], IDENTITY[2], IDENTITY[3], 0)])
def test_approved_flag_cannot_enable_unknown_source_run_or_draft(tmp_path, monkeypatch, identity):
    current = bind(tmp_path / 'pins.json', identity)
    current.PIN_PATH.write_text(json.dumps(pins(current))); monkeypatch.setattr(current, 'api', Mock())
    with pytest.raises(RuntimeError, match='incomplete'): current.main()
    current.api.assert_not_called()


@pytest.mark.parametrize('field,changed', [('repo', 'other/repo'), ('release_id', 999), ('tag', 'local-server-v9.9.9'),
                                         ('source', 'b' * 40), ('run_id', 999)])
def test_changed_identity_is_refused_before_api(engine, monkeypatch, field, changed):
    p = pins(engine); p[field] = changed; engine.PIN_PATH.write_text(json.dumps(p))
    monkeypatch.setattr(engine, 'api', Mock())
    with pytest.raises(RuntimeError, match='identity'): engine.main()
    engine.api.assert_not_called()


@pytest.mark.parametrize('change', ['unknown_asset', 'old_payload', 'old_artifact', 'missing_artifact', 'missing_proof'])
def test_new_fixed_asset_and_artifact_allowlists_are_strict(engine, change):
    p = pins(engine)
    if change == 'unknown_asset': p['assets']['unknown'] = p['body']
    if change == 'old_payload': p['assets']['IdolyPride-ServerData-v0.3.1.zip'] = p['assets'].pop(engine.PAYLOAD)
    if change == 'old_artifact': p['artifacts']['android']['name'] = 'android-server-build-and-available-evidence-v0.3.1'
    if change == 'missing_artifact': del p['artifacts']['macos']
    if change == 'missing_proof': p['proof'] = None
    engine.PIN_PATH.write_text(json.dumps(p))
    with pytest.raises(RuntimeError): engine.load_pins()


@pytest.mark.parametrize('change', ['body', 'source', 'published', 'unknown_asset'])
def test_legacy_draft_guards_retain_new_identity_and_body(engine, change):
    p = engine.load_pins(); d = value(p)
    if change == 'body': d['body'] = 'changed'
    if change == 'source': d['target_commitish'] = 'b' * 40
    if change == 'published': d['draft'] = False
    if change == 'unknown_asset': d['assets'] = [{'name': 'unknown'}]
    with pytest.raises(RuntimeError): engine.verify_draft(p, d, {})


def test_new_stage_reuses_fresh_guards_before_all_seven_posts(engine, monkeypatch, tmp_path):
    p = engine.load_pins(); rows = {}; operations = []
    def get(*_): operations.append('draft'); return value(p, rows)
    def tag(*_): operations.append('tag')
    def upload(_p, name, _path):
        assert operations[-2:] == ['tag', 'draft']
        operations.append('post'); rows[name] = {'id': len(rows)+1, 'name': name, 'size': 1,
            'digest': 'sha256:' + engine.sha(b'x'), 'state': 'uploaded'}
    monkeypatch.setattr(engine, 'api', get); monkeypatch.setattr(engine, 'verify_tag', tag)
    monkeypatch.setattr(engine, 'upload', upload)
    result = engine.stage(p, tmp_path)
    assert operations.count('post') == 7 and result['tag'] == IDENTITY[2]
    assert result['publication_performed'] is False and result['tag_or_release_metadata_modified'] is False


def test_concurrent_unknown_asset_aborts_before_second_post(engine, monkeypatch, tmp_path):
    p = engine.load_pins(); rows = {}; posts = []
    monkeypatch.setattr(engine, 'api', lambda *_: value(p, rows)); monkeypatch.setattr(engine, 'verify_tag', Mock())
    def upload(_p, name, _path):
        posts.append(name); rows[name] = {'id': 1, 'name': name, 'size': 1, 'digest': 'sha256:'+engine.sha(b'x'), 'state': 'uploaded'}
        rows['unknown'] = {'name': 'unknown'}
    monkeypatch.setattr(engine, 'upload', upload)
    with pytest.raises(RuntimeError): engine.stage(p, tmp_path)
    assert len(posts) == 1


def test_workflow_has_only_env_proof_inputs_and_fails_pins_before_download():
    text = (REPO / '.github/workflows/stage-reviewed-server-v032-draft.yml').read_text()
    assert 'IDOLY_REVIEW_BUNDLE_B64: ${{ inputs.review_bundle_b64 }}' in text
    assert text.index('configured_engine().load_pins()') < text.index('uses: actions/download-artifact@v4')
    assert 'persist-credentials: false' in text
    assert len(set(re.findall(r'run-id: (\d+)', text))) == 1
    assert not re.search(r'run:.*\$\{\{\s*inputs\.', text)
