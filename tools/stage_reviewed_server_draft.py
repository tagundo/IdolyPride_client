#!/usr/bin/env python3
"""Upload one reviewed v0.3.0 bundle to its existing draft; never publish it.

The dedicated Actions workflow supplies a real, repository-scoped GITHUB_TOKEN.
All source runs, files, hashes, release identity and tag are fixed here. No URL,
repository, release, source commit or local file can be selected by an input.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import urllib.parse
import urllib.request
from zipfile import ZipFile

REPO = 'tagundo/IdolyPride_client'
RELEASE = 440244669
TAG = 'local-server-v0.3.0'
SOURCE = 'b1af4bff3b98eb74c138fce24fab4f67d9d93e71'
RUN = 42889776755
PROOF_SHA = '2b77f57a14603e30ae217541f883d12ac36b185b132b5a8d9befb61526be33c5'
BODY_SHA = '937e73f462f8cb6c7281d4034c5b0524d211e47277140582ce25cc5caeb17374'
EXPECTED = {
 'IdolyPride-Local-Server-Android-QA.zip': (16451, '2bd989c7f722888f912c37bc80d126b1593df781e5233a497bb21da54a66ffb1'),
 'IdolyPride-Local-Server-Android.apk': (96574422, '817770d2cf86b60864fff9775f7fc2822d425e7e2819a60f331e423606d043b5'),
 'IdolyPride-Local-Server-macOS-QA.zip': (7242, '2a168307160ff3323601070deb01c46630d7b14c78014420afb0134910e26133'),
 'IdolyPride-Local-Server-macOS-arm64.app.zip': (94832653, 'b661664a8ca99403ee717f4df08056079df9d9bcd1a6b90f82c9a9f7f8a1e25d'),
 'IdolyPride-ServerData-v0.3.0.zip': (80929314, '3139ea69af1305a231ca09a3caab88a4496f1663c7a3af30892c588ed2cbc436'),
 'RELEASE-VERIFICATION.json': (6246, 'b50ac38caba947898162bab35bf520eae67e166b9d6020feb0f605371b721f99'),
 'SHA256SUMS': (519, '1eda40cc8941fbf92850b08a7d047008ecd6ab1a06fa92e533ae018f9646e86f'),
}
OLD = {
 'IdolyPride-Local-Server-macOS-arm64.app.zip': (731458081, 94633315, 'f1cbabf133015587ed2cd72e9f2d80fdf8eded7f92d70a4314d277e72030cb99'),
 'IdolyPride-Local-Server-macOS-QA.zip': (731458082, 7266, 'd34c4559af97a75bb484da39fc40beb9a7c63e0f42dae13772042522f561ed9e'),
 'IdolyPride-ServerData-v0.3.0.zip': (731453676, 80714001, '185276116e272c372398c534b7833a291086f203564b288cd889ce14c3ab8cfd'),
}
ARTIFACTS = {
 'android-server-build-and-available-evidence-v0.3.0': (13798242102, 'a85e4265de9f8e66b4f56ca86bf243920673a01b5030000447871da7997387de'),
 'macos-server-candidate-and-native-evidence-v0.3.0': (13797448790, 'a4c16c71f0b94349636ba6913c73a6313be6d20abd29b0d3e5c668cd9e21ae8c'),
}
BODY_NAME = 'RELEASE-BODY.ko.md'
PROOF_NAMES = frozenset(('IdolyPride-Local-Server-Android-QA.zip', 'RELEASE-VERIFICATION.json', 'SHA256SUMS', BODY_NAME))


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


def sha(raw): return hashlib.sha256(raw).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def checked(raw, name):
    size, digest = (3542, BODY_SHA) if name == BODY_NAME else EXPECTED[name]
    need(len(raw) == size and sha(raw) == digest, 'Reviewed bytes differ: ' + name)


def safe_members(archive, *, allow_symlinks=False):
    seen = set()
    for item in archive.infolist():
        name, path = item.filename, PurePosixPath(item.filename)
        need(name and not path.is_absolute() and '..' not in path.parts and '\\' not in name and '\0' not in name,
             'Unsafe ZIP member')
        need(name not in seen, 'Duplicate ZIP member')
        seen.add(name)
        need(allow_symlinks or not stat.S_ISLNK(item.external_attr >> 16), 'Unexpected ZIP symlink')
    return seen


def decode_proof(encoded, supplied_sha):
    need(isinstance(encoded, str) and len(encoded) == 28392 and supplied_sha == PROOF_SHA,
         'Unexpected approved proof input size/hash')
    raw = base64.b64decode(encoded, validate=True)
    need(len(raw) == 21292 and sha(raw) == PROOF_SHA, 'Proof envelope bytes changed')
    with ZipFile(io.BytesIO(raw)) as archive:
        need(safe_members(archive) == PROOF_NAMES and archive.testzip() is None, 'Unexpected proof members/CRC')
        files = {name: archive.read(name) for name in sorted(PROOF_NAMES)}
    for name, content in files.items(): checked(content, name)
    return files


def command(argv):
    result = subprocess.run(argv, text=True, capture_output=True, timeout=240)
    need(result.returncode == 0, 'GitHub command failed: ' + ' '.join(argv[:4]) + ': ' + result.stderr.strip())
    return result.stdout


def api(path):
    # GET only. The sole mutation below is one fixed-tag release asset upload.
    return json.loads(command(['gh', 'api', 'repos/' + REPO + '/' + path]))


def delete_reviewed_old_asset(ident):
    need(ident in {row[0] for row in OLD.values()}, 'Only the three reviewed old asset IDs may be deleted')
    command(['gh', 'api', '--method', 'DELETE', 'repos/' + REPO + '/releases/assets/' + str(ident)])


def draft(): return api('releases/' + str(RELEASE))


def verify_draft(value, inventory):
    need(value.get('id') == RELEASE and value.get('tag_name') == TAG and value.get('target_commitish') == SOURCE
         and value.get('draft') is True and value.get('prerelease') is True,
         'Dedicated draft identity/source/status changed')
    need(sha(value.get('body', '').encode()) == BODY_SHA, 'Reviewed draft body changed')
    rows = value.get('assets', [])
    need(len(rows) == len(inventory), 'Unexpected draft asset count')
    actual = {row['name']: row for row in rows}
    need(set(actual) == set(inventory), 'Unknown/missing/concurrent draft asset')
    for name, expected in inventory.items():
        row = actual[name]
        need((row.get('id'), row.get('size'), row.get('digest')) ==
             (expected[0], expected[1], 'sha256:' + expected[2]), 'Concurrent/unreviewed draft asset: ' + name)
    return actual


def verify_tag():
    tag = api('git/ref/tags/' + TAG)
    need(tag.get('ref') == 'refs/tags/' + TAG and tag['object'].get('type') == 'commit'
         and tag['object'].get('sha') == SOURCE, 'Tag differs from compiled source')


def verify_run():
    run = api('actions/runs/' + str(RUN))
    need(run.get('id') == RUN and run.get('head_sha') == SOURCE and run.get('status') == 'completed'
         and run.get('conclusion') == 'success', 'Pinned candidate run is not successful/exact source')
    jobs = {row['name']: row['conclusion'] for row in api('actions/runs/' + str(RUN) + '/jobs?per_page=100')['jobs']}
    need(all(jobs.get(name) == 'success' for name in ('prepare', 'android', 'macos')), 'Candidate native build jobs failed')
    artifacts = api('actions/runs/' + str(RUN) + '/artifacts?per_page=100')['artifacts']
    for name, (ident, digest) in ARTIFACTS.items():
        matches = [row for row in artifacts if row['name'] == name]
        need(len(matches) == 1 and matches[0]['id'] == ident and matches[0].get('expired') is False
             and matches[0].get('digest') == 'sha256:' + digest, 'Pinned Actions artifact differs: ' + name)


def prepare_files(directory, proof):
    directory.mkdir(parents=True, exist_ok=True)
    for name, content in proof.items(): (directory / name).write_bytes(content)
    for name, path in {
        'IdolyPride-Local-Server-Android.apk': Path('data/android/dist/IdolyPride-Local-Server-Android.apk'),
        'IdolyPride-Local-Server-macOS-arm64.app.zip': Path('data/macos/dist/IdolyPride-Local-Server-macOS-arm64.app.zip'),
        'IdolyPride-Local-Server-macOS-QA.zip': Path('data/macos/dist/IdolyPride-Local-Server-macOS-QA.zip'),
    }.items():
        need(path.is_file() and not path.is_symlink() and path.stat().st_size == EXPECTED[name][0]
             and file_sha(path) == EXPECTED[name][1], 'Downloaded candidate differs: ' + name)
        with ZipFile(path) as archive: safe_members(archive, allow_symlinks=name.endswith('.app.zip'))
        shutil.copyfile(path, directory / name)
    payload = directory / 'IdolyPride-ServerData-v0.3.0.zip'
    with ZipFile(directory / 'IdolyPride-Local-Server-macOS-arm64.app.zip') as archive:
        member = 'IdolyPrideLocalServer.app/Contents/Resources/ServerData.zip'
        need(archive.getinfo(member).file_size == EXPECTED[payload.name][0], 'Embedded public payload size differs')
        with archive.open(member) as source, payload.open('wb') as target: shutil.copyfileobj(source, target)
    for name, (size, digest) in EXPECTED.items():
        path = directory / name
        need(path.stat().st_size == size and file_sha(path) == digest, 'Final reviewed file mismatch: ' + name)
    with ZipFile(payload) as archive:
        names = safe_members(archive)
        need(len(names) == 265 and all(name.startswith('data/') for name in names), 'Unexpected public payload members')
        manifest = json.loads(archive.read('data/payload-manifest.json'))
        need(manifest.get('schema') == 1 and len(manifest['tables']) == 40 and 'Mission' in manifest['tables'],
             'Expected exact 40-table payload')
        need({row['path'] for row in manifest['files']} | {'data/payload-manifest.json'} == names,
             'Payload member set differs from its manifest')
        for row in manifest['files']:
            raw = archive.read(row['path'])
            need(len(raw) == row['bytes'] and sha(raw) == row['sha256'], 'Payload file does not match its manifest')
    local = json.loads((directory / 'RELEASE-VERIFICATION.json').read_text())
    need(local.get('compiled_source_commit') == SOURCE and local.get('independent_final_manifest_review_complete') is True,
         'Local final review manifest is not approved for this source')
    sums = (directory / 'SHA256SUMS').read_text().splitlines()
    expected_sums = {name: digest for name, (_size, digest) in EXPECTED.items()
                     if name not in ('RELEASE-VERIFICATION.json', 'SHA256SUMS')}
    need(len(sums) == 5 and dict(line.split('  ', 1)[::-1] for line in sums) == expected_sums,
         'Checksum file does not cover exactly five data/app/QA files')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        raise RuntimeError('Unexpected redirect from fixed GitHub asset upload endpoint')


def upload_asset(name, path):
    need(name in EXPECTED and path.name == name and os.environ.get('GITHUB_ACTIONS') == 'true',
         'Only fixed reviewed asset names may be uploaded by the dedicated Actions job')
    size, digest = EXPECTED[name]
    need(path.stat().st_size == size and file_sha(path) == digest, 'Reviewed file changed before upload')
    token = os.environ.get('GH_TOKEN', '')
    need(bool(token), 'Repository-scoped Actions token is unavailable')
    url = ('https://uploads.github.com/repos/' + REPO + '/releases/' + str(RELEASE)
           + '/assets?name=' + urllib.parse.quote(name, safe=''))
    # Streaming body, fixed host/release ID, TLS enabled, no credential-bearing
    # redirects. The token is never placed in logs, files or result reports.
    opener = urllib.request.build_opener(NoRedirect())
    with path.open('rb') as body:
        request = urllib.request.Request(url, data=body, method='POST', headers={
            'Authorization': 'Bearer ' + token, 'Content-Type': 'application/octet-stream',
            'Content-Length': str(size), 'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28'})
        with opener.open(request, timeout=240) as response:
            need(response.status == 201, 'Fixed asset upload did not return 201')
            result = json.load(response)
    need(result.get('name') == name and result.get('size') == size, 'Upload response identity/size mismatch')


def stage_assets(directory):
    inventory = dict(OLD)
    verify_tag()
    verify_draft(draft(), inventory)
    order = sorted(set(EXPECTED) - set(OLD)) + sorted(OLD)
    uploaded = []
    for name in order:
        verify_tag()
        verify_draft(draft(), inventory)  # Fresh guard before every replace/upload.
        if name in OLD:
            # The fresh inventory guard above binds the exact old ID/hash.
            delete_reviewed_old_asset(inventory[name][0])
            del inventory[name]
            verify_tag()
            verify_draft(draft(), inventory)  # Fresh guard again before POST.
        upload_asset(name, directory / name)
        current = draft()
        # Other names/IDs/digests must remain exactly as last observed.
        others = {key: value for key, value in inventory.items() if key != name}
        filtered = {**current, 'assets': [row for row in current.get('assets', []) if row['name'] != name]}
        verify_draft(filtered, others)
        matches = [row for row in current['assets'] if row['name'] == name]
        size, digest = EXPECTED[name]
        need(len(matches) == 1 and matches[0].get('size') == size
             and matches[0].get('digest') == 'sha256:' + digest and matches[0].get('state') == 'uploaded',
             'Uploaded size/server SHA mismatch: ' + name)
        inventory[name] = (matches[0]['id'], size, digest)
        uploaded.append({'name': name, 'id': matches[0]['id'], 'bytes': size, 'sha256': digest})
        print(json.dumps({'draft_asset_verified': name, 'bytes': size}), flush=True)
    final = draft()
    verify_draft(final, inventory)
    verify_tag()
    need(set(inventory) == set(EXPECTED), 'Draft asset set is not exactly seven')
    return {'draft_staging_passed': True, 'release_id': RELEASE, 'tag': TAG, 'draft': True,
        'compiled_source_commit': SOURCE, 'uploader_source_commit': os.environ.get('GITHUB_SHA'),
        'candidate_run_id': RUN, 'all_seven_server_sizes_sha256_verified': True,
        'reviewed_body_sha256': BODY_SHA, 'asset_count': 7, 'assets': uploaded,
        'publication_performed': False, 'tag_or_release_metadata_modified': False}


def main():
    proof = decode_proof(os.environ.get('IDOLY_REVIEW_BUNDLE_B64'), os.environ.get('IDOLY_REVIEW_BUNDLE_SHA256'))
    verify_run()
    directory = Path('data/reviewed-draft')
    prepare_files(directory, proof)
    output = Path('data/draft-staging-evidence'); output.mkdir(parents=True, exist_ok=True)
    try:
        report = stage_assets(directory)
    except Exception as error:
        (output / 'draft-staging-failure.json').write_text(json.dumps({
            'draft_staging_passed': False, 'error_class': type(error).__name__,
            'publication_performed': False, 'detail': 'See credential-masked Actions job log; no raw logs or tokens bundled'},
            indent=2) + '\n')
        raise
    (output / 'draft-staging-verification.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report), flush=True)


if __name__ == '__main__': main()
