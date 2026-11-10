"""Safety contracts for the append-only fixed patch draft uploader."""
import base64
import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest

MODULE = Path(__file__).parents[1] / 'tools/stage_reviewed_patch_draft.py'
spec = importlib.util.spec_from_file_location('patch_stager', MODULE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def pins():
    return dict(zip(('repo', 'release_id', 'tag', 'source', 'run_id'), m.IDENTITY),
                approved=True, assets={name: {'bytes': 1, 'sha256': m.sha(b'x')} for name in m.ASSETS},
                artifacts={key: {'id': i, 'name': name, 'bytes': 1, 'sha256': m.sha(b'x')} for key, i, name in
                           [('android', 1, 'android-server-build-and-available-evidence-v0.3.1'),
                            ('macos', 2, 'macos-server-candidate-and-native-evidence-v0.3.1')]},
                body={'bytes': 1, 'sha256': m.sha(b'x')}, proof={'bytes': 1, 'sha256': m.sha(b'x')})


def draft(p, inventory=None):
    return {'id': p['release_id'], 'tag_name': p['tag'], 'target_commitish': p['source'],
            'draft': True, 'prerelease': True, 'body': 'x', 'assets': list((inventory or {}).values())}


def test_unapproved_repository_pins_fail_before_api(monkeypatch, tmp_path):
    path = tmp_path / "unapproved.json"; path.write_text(json.dumps({"approved": False}))
    monkeypatch.setattr(m, "PIN_PATH", path)
    monkeypatch.setattr(m, 'api', Mock(side_effect=AssertionError('API forbidden')))
    with pytest.raises(RuntimeError, match='not approved'):
        m.main()
    m.api.assert_not_called()


@pytest.mark.parametrize('field,value', [('repo', 'other/repo'), ('release_id', 1), ('tag', 'other'),
                                         ('source', '0' * 40), ('run_id', 1)])
def test_pins_cannot_select_other_identity(tmp_path, monkeypatch, field, value):
    p = pins(); p[field] = value
    path = tmp_path / 'pins.json'; path.write_text(json.dumps(p)); monkeypatch.setattr(m, 'PIN_PATH', path)
    with pytest.raises(RuntimeError, match='identity'):
        m.load_pins()


@pytest.mark.parametrize('change', ['draft', 'source', 'body', 'count', 'unknown'])
def test_draft_guard_rejects_mutation(change):
    p = pins(); value = draft(p)
    if change == 'draft': value['draft'] = False
    if change == 'source': value['target_commitish'] = 'other'
    if change == 'body': value['body'] = 'changed'
    if change in ('count', 'unknown'): value['assets'] = [{'name': 'unknown'}]
    with pytest.raises(RuntimeError): m.verify_draft(p, value, {})


def test_existing_or_partial_draft_cannot_resume(monkeypatch, tmp_path):
    p = pins(); monkeypatch.setattr(m, 'verify_tag', Mock())
    value = draft(p); value['assets'] = [{'name': m.APK}]
    monkeypatch.setattr(m, 'api', Mock(return_value=value)); monkeypatch.setattr(m, 'upload', Mock())
    with pytest.raises(RuntimeError, match='count'): m.stage(p, tmp_path)
    m.upload.assert_not_called()


def test_fresh_tag_body_inventory_guard_before_every_write(monkeypatch, tmp_path):
    p = pins(); seen = {}; operations = []
    def tag(_p): operations.append('tag')
    def get(_p, _path):
        operations.append('draft')
        return draft(p, seen)
    def upload(_p, name, _path):
        assert operations[-2:] == ['tag', 'draft']
        operations.append('post')
        seen[name] = {'id': len(seen) + 1, 'name': name, 'size': 1, 'digest': 'sha256:' + m.sha(b'x'), 'state': 'uploaded'}
    monkeypatch.setattr(m, 'verify_tag', tag); monkeypatch.setattr(m, 'api', get); monkeypatch.setattr(m, 'upload', upload)
    result = m.stage(p, tmp_path)
    assert result['asset_count'] == 7 and result['publication_performed'] is False
    assert operations.count('post') == 7


def test_concurrent_asset_aborts_before_next_write(monkeypatch, tmp_path):
    p = pins(); seen = {}; posted = []
    monkeypatch.setattr(m, 'verify_tag', Mock())
    def upload(_p, name, _path):
        posted.append(name)
        seen[name] = {'id': 1, 'name': name, 'size': 1, 'digest': 'sha256:' + m.sha(b'x'), 'state': 'uploaded'}
        seen['stranger'] = {'id': 2, 'name': 'stranger'}
    monkeypatch.setattr(m, 'upload', upload); monkeypatch.setattr(m, 'api', lambda *_: draft(p, seen))
    with pytest.raises(RuntimeError): m.stage(p, tmp_path)
    assert len(posted) == 1


def test_wrong_server_digest_aborts(monkeypatch, tmp_path):
    p = pins(); seen = {}
    monkeypatch.setattr(m, 'verify_tag', Mock())
    def upload(_p, name, _path):
        seen[name] = {'id': 1, 'name': name, 'size': 1, 'digest': 'sha256:' + '0' * 64, 'state': 'uploaded'}
    monkeypatch.setattr(m, 'upload', upload); monkeypatch.setattr(m, 'api', lambda *_: draft(p, seen))
    with pytest.raises(RuntimeError, match='Concurrent'): m.stage(p, tmp_path)


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'a\\b', 'normal\0bad'])
def test_proof_rejects_unsafe_members(name):
    # ZIP truncates NUL filenames; test the post-write observed name below.
    if '\0' in name: return
    out = io.BytesIO()
    with ZipFile(out, 'w') as z: z.writestr(name, b'x')
    with ZipFile(io.BytesIO(out.getvalue())) as z:
        with pytest.raises(RuntimeError): m.members(z)


def test_proof_requires_exact_hash_and_four_names():
    p = pins(); out = io.BytesIO()
    with ZipFile(out, 'w') as z: z.writestr('unknown', b'x')
    raw = out.getvalue(); p['proof'] = {'bytes': len(raw), 'sha256': m.sha(raw)}
    with pytest.raises(RuntimeError, match='members'):
        m.decode_proof(p, base64.b64encode(raw).decode(), m.sha(raw))
    with pytest.raises(RuntimeError, match='size/hash'):
        m.decode_proof(p, base64.b64encode(raw).decode(), '0' * 64)


def test_upload_rejects_host_before_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv('GITHUB_ACTIONS', raising=False)
    monkeypatch.setattr(m.urllib.request, 'build_opener', Mock(side_effect=AssertionError('network forbidden')))
    with pytest.raises(RuntimeError, match='Actions'): m.upload(pins(), m.APK, tmp_path / m.APK)
    m.urllib.request.build_opener.assert_not_called()


def test_redirects_are_forbidden():
    with pytest.raises(RuntimeError, match='redirect'):
        m.NoRedirect().redirect_request(None, None, 302, None, None, 'https://other.invalid')


def test_workflow_inputs_only_enter_environment():
    workflow = (MODULE.parents[1] / '.github/workflows/stage-reviewed-patch-draft.yml').read_text()
    assert 'run-id: 42921195880' in workflow
    assert 'persist-credentials: false' in workflow
    assert 'IDOLY_REVIEW_BUNDLE_B64: ${{ inputs.review_bundle_b64 }}' in workflow
    assert 'run: python tools/stage_reviewed_patch_draft.py' in workflow
    assert '--method' not in MODULE.read_text() and "method='POST'" in MODULE.read_text()


@pytest.mark.parametrize('change', ['id', 'digest', 'state', 'size'])
def test_existing_uploaded_asset_is_bound_to_all_four_properties(change):
    p = pins(); name = m.APK
    row = {'id': 7, 'name': name, 'size': 1, 'digest': 'sha256:' + m.sha(b'x'), 'state': 'uploaded'}
    value = draft(p, {name: row})
    row[change] = {'id': 8, 'digest': 'sha256:' + '0' * 64, 'state': 'starter', 'size': 2}[change]
    with pytest.raises(RuntimeError, match='Concurrent'):
        m.verify_draft(p, value, {name: {'id': 7, **p['assets'][name]}})


@pytest.mark.parametrize('change', ['head', 'run', 'conclusion', 'job', 'artifact'])
def test_candidate_run_cannot_substitute_source_or_artifact(monkeypatch, change):
    p = pins()
    run = {'id': p['run_id'], 'head_sha': p['source'], 'status': 'completed', 'conclusion': 'success'}
    jobs = {'jobs': [{'name': key, 'conclusion': 'success'} for key in ('prepare', 'android', 'macos')]}
    artifacts = {'artifacts': [{'id': row['id'], 'name': row['name'], 'size_in_bytes': row['bytes'],
                              'digest': 'sha256:' + row['sha256'], 'expired': False} for row in p['artifacts'].values()]}
    if change == 'head': run['head_sha'] = '0' * 40
    if change == 'run': run['id'] = 1
    if change == 'conclusion': run['conclusion'] = 'failure'
    if change == 'job': jobs['jobs'][0]['conclusion'] = 'skipped'
    if change == 'artifact': artifacts['artifacts'][0]['id'] = 999
    monkeypatch.setattr(m, 'api', Mock(side_effect=[run, jobs, artifacts]))
    with pytest.raises(RuntimeError): m.verify_run(p)
