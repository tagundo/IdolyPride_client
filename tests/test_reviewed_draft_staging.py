"""A draft becoming public/concurrently changed must stop before another write."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SPEC = importlib.util.spec_from_file_location('reviewed_draft_stager',
    Path(__file__).resolve().parents[1] / 'tools/stage_reviewed_server_draft.py')
stage = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stage)


def release(inventory):
    return {'id': stage.RELEASE, 'tag_name': stage.TAG, 'target_commitish': stage.SOURCE,
        'draft': True, 'prerelease': True, 'body': 'reviewed body',
        'assets': [{'name': name, 'id': row[0], 'size': row[1], 'digest': 'sha256:' + row[2],
                    'state': 'uploaded'} for name, row in inventory.items()]}


@pytest.fixture
def owned(monkeypatch):
    real_sha = stage.sha
    monkeypatch.setattr(stage, 'sha', lambda raw: stage.BODY_SHA if raw == b'reviewed body' else real_sha(raw))
    return release(stage.OLD)


@pytest.mark.parametrize('field,value', [('id', 1), ('tag_name', 'other-tag'),
    ('target_commitish', 'a' * 40), ('draft', False), ('prerelease', False), ('body', 'changed')])
def test_draft_identity_source_body_and_visibility_are_all_required(owned, field, value):
    changed = {**owned, field: value}
    with pytest.raises(RuntimeError): stage.verify_draft(changed, stage.OLD)


@pytest.mark.parametrize('change', ['unknown', 'duplicate', 'missing', 'wrong_id', 'wrong_size', 'wrong_hash'])
def test_concurrent_asset_changes_never_qualify_for_replacement(owned, change):
    if change == 'unknown': owned['assets'][0]['name'] = 'other.apk'
    elif change == 'duplicate': owned['assets'].append(deepcopy(owned['assets'][0]))
    elif change == 'missing': owned['assets'].pop()
    elif change == 'wrong_id': owned['assets'][0]['id'] += 1
    elif change == 'wrong_size': owned['assets'][0]['size'] += 1
    else: owned['assets'][0]['digest'] = 'sha256:' + 'a' * 64
    with pytest.raises(RuntimeError): stage.verify_draft(owned, stage.OLD)


def test_unknown_old_id_cannot_be_deleted(monkeypatch):
    monkeypatch.setattr(stage, 'command', lambda argv: pytest.fail('No delete request may be made'))
    with pytest.raises(RuntimeError): stage.delete_reviewed_old_asset(1)


@pytest.mark.parametrize('publish_after', [None, 'first_post', 'first_delete'])
def test_each_post_and_delete_is_guarded_even_after_prior_valid_writes(owned, monkeypatch, tmp_path, publish_after):
    state = owned
    writes = []

    def api(path):
        if path == 'git/ref/tags/' + stage.TAG:
            return {'ref': 'refs/tags/' + stage.TAG, 'object': {'type': 'commit', 'sha': stage.SOURCE}}
        assert path == 'releases/' + str(stage.RELEASE)
        return deepcopy(state)

    def command(argv):
        if argv[:4] == ['gh', 'api', '--method', 'DELETE']:
            ident = int(argv[-1].rsplit('/', 1)[1])
            assert ident in {row[0] for row in stage.OLD.values()}
            state['assets'] = [row for row in state['assets'] if row['id'] != ident]
            writes.append(('delete', ident))
            if publish_after == 'first_delete': state['draft'] = False
        else:
            raise AssertionError('Only the exact old asset DELETE may use gh command mutation')
        return ''

    def upload_asset(name, path):
        assert path.name == name
        assert name in stage.EXPECTED and not any(row['name'] == name for row in state['assets'])
        size, digest = stage.EXPECTED[name]
        state['assets'].append({'name': name, 'id': 100000 + len(writes), 'size': size,
                                'digest': 'sha256:' + digest, 'state': 'uploaded'})
        writes.append(('post', name))
        if publish_after == 'first_post': state['draft'] = False

    monkeypatch.setattr(stage, 'api', api)
    monkeypatch.setattr(stage, 'command', command)
    monkeypatch.setattr(stage, 'upload_asset', upload_asset)
    if publish_after is not None:
        with pytest.raises(RuntimeError): stage.stage_assets(tmp_path)
        assert len(writes) == (1 if publish_after == 'first_post' else 5)
    else:
        result = stage.stage_assets(tmp_path)
        assert result['draft_staging_passed'] is True and result['publication_performed'] is False
        assert len(writes) == 10  # Seven POSTs; only the three exact old IDs deleted.
        assert sum(kind == 'delete' for kind, _ in writes) == 3
        assert {row['name'] for row in state['assets']} == set(stage.EXPECTED)
