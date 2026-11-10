#!/usr/bin/env python3
"""Append exactly seven pinned assets to one empty reviewed draft; never publish.

The workflow has no repository/release/source/path selector. Future patches may
reuse this engine with another reviewed, repository-committed pin file.
"""
from __future__ import annotations
import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import urllib.parse
import urllib.request
from zipfile import ZipFile

PIN_PATH = Path(__file__).with_name('reviewed-drafts') / 'local-server-v0.3.1.json'
IDENTITY = ('tagundo/IdolyPride_client', 441044576, 'local-server-v0.3.1',
            '6e06100a8fd4ab767f97011f48760e1e7b70a8e4', 42921195880)
BODY = 'RELEASE-BODY.ko.md'
QA = 'IdolyPride-Local-Server-Android-QA.zip'
APK = 'IdolyPride-Local-Server-Android.apk'
MAC = 'IdolyPride-Local-Server-macOS-arm64.app.zip'
MAC_QA = 'IdolyPride-Local-Server-macOS-QA.zip'
PAYLOAD = 'IdolyPride-ServerData-v0.3.1.zip'
ASSETS = frozenset((QA, APK, MAC, MAC_QA, PAYLOAD, 'SHA256SUMS', 'RELEASE-VERIFICATION.json'))
PROOF = frozenset((QA, 'SHA256SUMS', 'RELEASE-VERIFICATION.json', BODY))


def need(value, detail):
    if not value:
        raise RuntimeError(detail)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def pin_record(row):
    return (isinstance(row, dict) and type(row.get('bytes')) is int and row['bytes'] > 0
            and isinstance(row.get('sha256'), str) and re.fullmatch('[0-9a-f]{64}', row['sha256']) is not None)


def load_pins():
    p = json.loads(PIN_PATH.read_text())
    need(p.get('approved') is True, 'Reviewed patch pins are not approved')
    need(tuple(p.get(k) for k in ('repo', 'release_id', 'tag', 'source', 'run_id')) == IDENTITY,
         'Dedicated patch identity changed')
    need(set(p.get('assets', {})) == ASSETS and all(pin_record(row) for row in p['assets'].values()),
         'Exactly seven complete asset pins are required')
    need(pin_record(p.get('body')) and pin_record(p.get('proof')), 'Missing body/proof pins')
    need(set(p.get('artifacts', {})) == {'android', 'macos'}, 'Both native artifacts must be pinned')
    for kind, row in p['artifacts'].items():
        need(pin_record(row) and type(row.get('id')) is int and row['id'] > 0
             and row.get('name') == {'android': 'android-server-build-and-available-evidence-v0.3.1',
                                     'macos': 'macos-server-candidate-and-native-evidence-v0.3.1'}[kind],
             'Invalid native artifact pin')
    return p


def checked(raw, row, name):
    need(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'Reviewed bytes changed: ' + name)


def members(z, *, symlinks=False):
    seen = set()
    for item in z.infolist():
        name, path = item.filename, PurePosixPath(item.filename)
        need(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name and '\0' not in name,
             'Unsafe ZIP member')
        need(name not in seen and (symlinks or not stat.S_ISLNK(item.external_attr >> 16)),
             'Duplicate or symlink ZIP member')
        seen.add(name)
    return seen


def decode_proof(p, encoded, supplied):
    need(isinstance(encoded, str) and len(encoded) == 4 * ((p['proof']['bytes'] + 2) // 3)
         and supplied == p['proof']['sha256'], 'Unexpected proof envelope size/hash')
    raw = base64.b64decode(encoded, validate=True)
    checked(raw, p['proof'], 'proof envelope')
    with ZipFile(io.BytesIO(raw)) as z:
        need(members(z) == PROOF and z.testzip() is None, 'Unexpected proof members/CRC')
        values = {name: z.read(name) for name in PROOF}
    for name, value in values.items():
        checked(value, p['body'] if name == BODY else p['assets'][name], name)
    return values


def api(p, path):
    result = subprocess.run(['gh', 'api', 'repos/' + p['repo'] + '/' + path],
                            text=True, capture_output=True, timeout=240)
    need(result.returncode == 0, 'GitHub read failed: ' + path)
    return json.loads(result.stdout)


def verify_tag(p):
    value = api(p, 'git/ref/tags/' + p['tag'])
    need(value.get('ref') == 'refs/tags/' + p['tag'] and value.get('object', {}).get('type') == 'commit'
         and value['object'].get('sha') == p['source'], 'Compiled source tag changed')


def verify_draft(p, value, inventory):
    need(value.get('id') == p['release_id'] and value.get('tag_name') == p['tag']
         and value.get('target_commitish') == p['source'] and value.get('draft') is True
         and value.get('prerelease') is True, 'Dedicated draft identity/status changed')
    body = value.get('body', '').encode()
    checked(body, p['body'], BODY)
    rows = value.get('assets', [])
    need(len(rows) == len(inventory), 'Unknown/concurrent draft asset count')
    actual = {row['name']: row for row in rows}
    need(set(actual) == set(inventory), 'Unknown/missing/concurrent draft asset')
    for name, row in inventory.items():
        seen = actual[name]
        need((seen.get('id'), seen.get('size'), seen.get('digest'), seen.get('state')) ==
             (row['id'], row['bytes'], 'sha256:' + row['sha256'], 'uploaded'), 'Concurrent draft asset: ' + name)


def verify_run(p):
    value = api(p, 'actions/runs/' + str(p['run_id']))
    need(value.get('id') == p['run_id'] and value.get('head_sha') == p['source']
         and value.get('status') == 'completed' and value.get('conclusion') == 'success', 'Pinned build did not pass')
    jobs = api(p, 'actions/runs/' + str(p['run_id']) + '/jobs?per_page=100')['jobs']
    need(all(any(r['name'] == key and r['conclusion'] == 'success' for r in jobs)
             for key in ('prepare', 'android', 'macos')), 'Native build jobs did not pass')
    rows = api(p, 'actions/runs/' + str(p['run_id']) + '/artifacts?per_page=100')['artifacts']
    for wanted in p['artifacts'].values():
        matches = [r for r in rows if r['name'] == wanted['name']]
        need(len(matches) == 1 and matches[0]['id'] == wanted['id'] and matches[0]['expired'] is False
             and matches[0].get('digest') == 'sha256:' + wanted['sha256']
             and matches[0].get('size_in_bytes') == wanted['bytes'], 'Native artifact identity changed')


def prepare_files(p, directory, proof):
    need(not directory.exists(), 'Staging directory must be new')
    directory.mkdir(parents=True)
    for name, raw in proof.items(): (directory / name).write_bytes(raw)
    for name, source in {APK: Path('data/android/dist') / APK,
                         MAC: Path('data/macos/dist') / MAC, MAC_QA: Path('data/macos/dist') / MAC_QA}.items():
        need(source.is_file() and not source.is_symlink(), 'Candidate must be a regular file')
        need(source.stat().st_size == p['assets'][name]['bytes'] and file_sha(source) == p['assets'][name]['sha256'],
             'Native candidate changed: ' + name)
        with ZipFile(source) as z: members(z, symlinks=name == MAC)
        shutil.copyfile(source, directory / name)
    with ZipFile(directory / MAC) as z:
        member = 'IdolyPrideLocalServer.app/Contents/Resources/ServerData.zip'
        need(z.getinfo(member).file_size == p['assets'][PAYLOAD]['bytes'], 'Payload embedded size changed')
        with z.open(member) as source, (directory / PAYLOAD).open('wb') as dest: shutil.copyfileobj(source, dest)
    for name, row in p['assets'].items():
        path = directory / name
        need(path.stat().st_size == row['bytes'] and file_sha(path) == row['sha256'], 'Prepared bytes changed: ' + name)
    local = json.loads(proof['RELEASE-VERIFICATION.json'])
    need(local.get('compiled_source_commit') == p['source'] and local.get('release_id') == p['release_id']
         and local.get('tag') == p['tag'] and local.get('independent_final_manifest_review_complete') is True,
         'Final independent manifest approval is absent')
    sums = proof['SHA256SUMS'].decode().splitlines()
    expected = {name: row['sha256'] for name, row in p['assets'].items()
                if name not in ('SHA256SUMS', 'RELEASE-VERIFICATION.json')}
    need(len(sums) == 5 and dict(line.split('  ', 1)[::-1] for line in sums) == expected,
         'Checksums must cover exactly five app/data/QA assets')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise RuntimeError('Unexpected redirect from fixed GitHub upload endpoint')


def upload(p, name, path):
    need(os.environ.get('GITHUB_ACTIONS') == 'true' and name in ASSETS and path.name == name,
         'Only the reviewed Actions job may upload fixed asset names')
    row = p['assets'][name]
    need(path.is_file() and not path.is_symlink() and path.stat().st_size == row['bytes']
         and file_sha(path) == row['sha256'], 'Asset changed before POST')
    token = os.environ.get('GH_TOKEN', '')
    need(token, 'Repository-scoped Actions token missing')
    url = ('https://uploads.github.com/repos/' + p['repo'] + '/releases/' + str(p['release_id'])
           + '/assets?name=' + urllib.parse.quote(name, safe=''))
    with path.open('rb') as body:
        request = urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/octet-stream',
            'Content-Length': str(row['bytes']), 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=240) as response:
            need(response.status == 201, 'Asset POST did not return 201')
            result = json.load(response)
    need(result.get('name') == name and result.get('size') == row['bytes'], 'POST response identity changed')


def stage(p, directory):
    inventory = {}
    for name in sorted(ASSETS):
        # No DELETE, overwrite, PATCH or tag mutation exists. A partially filled
        # or concurrent draft fails closed and requires a new human review.
        verify_tag(p)
        verify_draft(p, api(p, 'releases/' + str(p['release_id'])), inventory)
        upload(p, name, directory / name)
        value = api(p, 'releases/' + str(p['release_id']))
        matches = [r for r in value.get('assets', []) if r['name'] == name]
        need(len(matches) == 1 and type(matches[0].get('id')) is int, 'New upload missing/duplicated')
        inventory[name] = {'id': matches[0]['id'], **p['assets'][name]}
        verify_draft(p, value, inventory)
        print(json.dumps({'draft_asset_verified': name}), flush=True)
    verify_tag(p)
    verify_draft(p, api(p, 'releases/' + str(p['release_id'])), inventory)
    return {'draft_staging_passed': True, 'release_id': p['release_id'], 'tag': p['tag'],
            'compiled_source_commit': p['source'], 'candidate_run_id': p['run_id'],
            'uploader_source_commit': os.environ.get('GITHUB_SHA'), 'trusted_pin_file_sha256': file_sha(PIN_PATH),
            'asset_count': 7, 'assets': inventory, 'draft': True,
            'publication_performed': False, 'tag_or_release_metadata_modified': False}


def main():
    p = load_pins()  # Approval/pins are checked before any API access.
    proof = decode_proof(p, os.environ.get('IDOLY_REVIEW_BUNDLE_B64'), os.environ.get('IDOLY_REVIEW_BUNDLE_SHA256'))
    verify_run(p)
    directory = Path('data/reviewed-patch-draft')
    prepare_files(p, directory, proof)
    output = Path('data/patch-draft-staging-evidence'); output.mkdir(parents=True, exist_ok=True)
    try:
        report = stage(p, directory)
    except Exception as error:
        (output / 'failure.json').write_text(json.dumps({'draft_staging_passed': False,
            'error_class': type(error).__name__, 'publication_performed': False}) + '\n')
        raise
    (output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n')


if __name__ == '__main__': main()
