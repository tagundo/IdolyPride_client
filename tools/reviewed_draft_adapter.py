"""Reuse the immutable reviewed v0.3.1 append-only uploader for a fixed patch.

Only repository-committed wrappers can supply identity, pin path, payload name
or artifact names. Workflow inputs still select only exact public proof bytes.
The legacy source must match its independent-review SHA before it is loaded.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re

ENGINE_PATH = Path(__file__).with_name('stage_reviewed_patch_draft.py')
ENGINE_SHA256 = '014da2d4118ab3095b458d533a88a9bb36bad0c7b49fd647f5b7508a9a43cef9'
REPOSITORY = 'tagundo/IdolyPride_client'


def need(value, message):
    if not value:
        raise RuntimeError(message)


def bind(*, identity, pin_path, payload_name, artifact_names):
    """Return an isolated copy of the pinned engine with a strict pin reader.

    This does not call an API, read credentials, stage files or mutate GitHub.
    Unknown identity placeholders are allowed for preparation, but load_pins
    refuses them before any API access even if someone flips approved:true.
    """
    need(hashlib.sha256(ENGINE_PATH.read_bytes()).hexdigest() == ENGINE_SHA256,
         'Immutable reviewed uploader source changed')
    need(len(identity) == 5 and identity[0] == REPOSITORY, 'Repository selector is forbidden')
    need(isinstance(identity[2], str) and re.fullmatch(r'local-server-v\d+\.\d+\.\d+', identity[2]),
         'Invalid fixed release tag')
    need(payload_name == 'IdolyPride-ServerData-' + identity[2].removeprefix('local-server-') + '.zip',
         'Payload filename must match the fixed patch tag')
    need(set(artifact_names) == {'android', 'macos'} and artifact_names == {
        'android': 'android-server-build-and-available-evidence-' + identity[2].removeprefix('local-server-'),
        'macos': 'macos-server-candidate-and-native-evidence-' + identity[2].removeprefix('local-server-')},
        'Native artifact names must match the fixed patch tag')
    spec = importlib.util.spec_from_file_location('_reviewed_patch_upload_engine', ENGINE_PATH)
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    engine.PIN_PATH = Path(pin_path)
    engine.IDENTITY = tuple(identity)
    engine.ASSETS = frozenset((engine.ASSETS - {engine.PAYLOAD}) | {payload_name})
    engine.PAYLOAD = payload_name

    def load_pins():
        p = json.loads(engine.PIN_PATH.read_text())
        need(p.get('approved') is True, 'Reviewed patch pins are not approved')
        repo, release, tag, source, run = identity
        need(type(release) is int and release > 0 and type(run) is int and run > 0
             and isinstance(source, str) and re.fullmatch('[0-9a-f]{40}', source),
             'Fixed compiled source, run and draft identity are incomplete')
        need(tuple(p.get(k) for k in ('repo', 'release_id', 'tag', 'source', 'run_id')) == tuple(identity),
             'Dedicated patch identity changed')
        need(set(p.get('assets', {})) == engine.ASSETS
             and all(engine.pin_record(row) for row in p['assets'].values()),
             'Exactly seven complete asset pins are required')
        need(engine.pin_record(p.get('body')) and engine.pin_record(p.get('proof')), 'Missing body/proof pins')
        need(set(p.get('artifacts', {})) == {'android', 'macos'}, 'Both native artifacts must be pinned')
        for kind, row in p['artifacts'].items():
            need(engine.pin_record(row) and type(row.get('id')) is int and row['id'] > 0
                 and row.get('name') == artifact_names[kind], 'Invalid native artifact pin')
        return p

    engine.load_pins = load_pins
    return engine
