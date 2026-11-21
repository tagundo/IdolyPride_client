"""Read-only admission for the one audited latest public master cohort."""
from __future__ import annotations
from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import threading

_FEATURES = frozenset(('story_reads', 'media_access', 'panorama', 'dream', 'main_live'))
_HEX = re.compile(r'[0-9a-f]{64}\Z')
_SCHEMA_SHA256 = '0fcf90596261dcd9bbed165bd93859dc30127e2a494e6529bafbd8885675edf3'
_MAX_CONTROLS_CACHE = 16
_MAX_MEMBER_CACHE = 512
_VERIFIED = OrderedDict()
_CONTROLS = OrderedDict()
_LOCK = threading.RLock()
_PREFIXES = frozenset(('master-json', 'original-master', 'public-story', 'public-tutorial', 'public-dream', 'protocol'))


def _need(value):
    if not value:
        raise ValueError('Unapproved or changed latest public master cohort')


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _need(key not in result)
        result[key] = value
    return result


def _open(path):
    return os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))


def _open_member(root, name):
    """Walk beneath an already resolved public root without following links."""
    _need(type(name) is str and '\\' not in name)
    relative = PurePosixPath(name)
    _need(bool(relative.parts) and not relative.is_absolute() and str(relative) == name
          and all(part not in ('', '.', '..') for part in relative.parts))
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    directory_flags = flags | getattr(os, 'O_DIRECTORY', 0)
    descriptor = os.open(root, directory_flags)
    try:
        _need(stat.S_ISDIR(os.fstat(descriptor).st_mode))
        parts = relative.parts
        for part in parts[:-1]:
            child = os.open(part, directory_flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
            _need(stat.S_ISDIR(os.fstat(descriptor).st_mode))
        return os.open(parts[-1], flags, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def _identity(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read_member(root, name, limit):
    with os.fdopen(_open_member(root, name), 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= limit)
        value = stream.read(limit + 1)
        _need(len(value) == before.st_size and _identity(os.fstat(stream.fileno())) == _identity(before))
        return value


def _verify_file(root, row):
    _need(type(row) is dict and set(row) == {'path', 'bytes', 'sha256'})
    name, size, digest = row['path'], row['bytes'], row['sha256']
    _need(type(name) is str and '\\' not in name and ':' not in name
          and all(ord(character) >= 32 and ord(character) != 127 for character in name))
    parts = PurePosixPath(name)
    _need(not parts.is_absolute() and len(parts.parts) >= 2 and parts.parts[0] in _PREFIXES
          and not any(part in ('', '.', '..') for part in parts.parts) and str(parts) == name)
    _need(type(size) is int and 0 < size <= 64 * 1024 * 1024 and type(digest) is str and _HEX.fullmatch(digest))
    with os.fdopen(_open_member(root, name), 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and before.st_size == size)
        key = (str(root), name, digest, _identity(before))
        with _LOCK:
            if key in _VERIFIED:
                _need(_identity(os.fstat(stream.fileno())) == _identity(before))
                _VERIFIED.move_to_end(key)
                return
        value, count = hashlib.sha256(), 0
        while block := stream.read(65536):
            count += len(block)
            _need(count <= size)
            value.update(block)
        _need(count == size and value.hexdigest() == digest
              and _identity(os.fstat(stream.fileno())) == _identity(before))
    with _LOCK:
        _VERIFIED[key] = True
        while len(_VERIFIED) > _MAX_MEMBER_CACHE:
            _VERIFIED.popitem(last=False)


def _parse_controls(raw, version):
    proof = json.loads(raw, object_pairs_hook=_pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid public cohort metadata')))
    _need(type(proof) is dict and set(proof) == {'schema', 'master_version', 'features'}
          and type(proof['schema']) is int and proof['schema'] == 1
          and proof['master_version'] == version
          and type(proof['features']) is dict
          and set(proof['features']) == _FEATURES | {'octo'})
    keys = {'status', 'scope', 'master_version', 'schema_sha256', 'receipt', 'receipt_sha256'}
    for feature, row in proof['features'].items():
        _need(type(row) is dict and set(row) == keys and row['status'] == 'PASS'
              and row['scope'] == feature and row['master_version'] == version
              and row['schema_sha256'] == _SCHEMA_SHA256 and type(row['receipt']) is dict
              and row['receipt'] and type(row['receipt_sha256']) is str
              and _HEX.fullmatch(row['receipt_sha256']))
        receipt = json.dumps(row['receipt'], sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode('utf-8')
        _need(row['receipt_sha256'] == hashlib.sha256(receipt).hexdigest())
    return proof


def _verified_controls(root, wanted, version):
    with os.fdopen(_open_member(root, 'latest-semantic-controls.json'), 'rb') as stream:
        before = os.fstat(stream.fileno())
        _need(stat.S_ISREG(before.st_mode) and 0 < before.st_size <= 512 * 1024)
        key = (str(root), wanted, version, _identity(before))
        with _LOCK:
            if key in _CONTROLS:
                _need(_identity(os.fstat(stream.fileno())) == _identity(before))
                _CONTROLS.move_to_end(key)
                return _CONTROLS[key]
        raw = stream.read(512 * 1024 + 1)
        _need(len(raw) == before.st_size and hashlib.sha256(raw).hexdigest() == wanted
              and _identity(os.fstat(stream.fileno())) == _identity(before))
        proof = _parse_controls(raw, version)
        _need(_identity(os.fstat(stream.fileno())) == _identity(before))
    with _LOCK:
        _CONTROLS[key] = proof
        while len(_CONTROLS) > _MAX_CONTROLS_CACHE:
            _CONTROLS.popitem(last=False)
    return proof


def _require(master_dir, feature):
    from . import latest_cohort_pins as pins
    _need(type(feature) is str and feature in _FEATURES and isinstance(master_dir, (str, os.PathLike)))
    _need(bool(os.fspath(master_dir)))
    supplied = Path(master_dir)
    _need(not supplied.is_symlink())
    directory = supplied.resolve(strict=True)
    _need(directory.is_dir() and directory.name == 'master-json')
    version, wanted = getattr(pins, 'MASTER_VERSION', None), getattr(pins, 'CONTROLS_SHA256', None)
    registry = getattr(pins, 'FEATURE_FILES', None)
    _need(type(version) is str and _HEX.fullmatch(version)
          and type(wanted) is str and _HEX.fullmatch(wanted)
          and type(registry) is dict and all(type(key) is str for key in registry)
          and set(registry) <= _FEATURES)
    root = directory.parent
    _need(_read_member(root, 'master-json/!version.txt', 4096).decode('utf-8').strip() == version)
    _verified_controls(root, wanted, version)
    files = registry.get(feature)
    _need(type(files) in (list, tuple) and 0 < len(files) <= 256
          and all(type(item) is dict for item in files))
    names = [item.get('path') for item in files]
    _need(all(type(name) is str for name in names) and names == sorted(set(names)))
    for item in files:
        _verify_file(root, item)
    return None


def require_master_cohort(master_dir, feature):
    """Require exact six-feature controls and every approved public file hash.

    The only successful result is None. Semantic/type failures raise ValueError;
    filesystem failures may raise OSError. No DB, profile, settings or save path
    is opened. Legacy callers retain their branch and never call this helper.
    """
    try:
        return _require(master_dir, feature)
    except (TypeError, UnicodeError, RecursionError, OverflowError):
        raise ValueError('Unapproved or changed latest public master cohort') from None
