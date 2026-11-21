"""Load protobuf descriptors without importing a game's login/client scripts."""

from __future__ import annotations

import hashlib
import importlib
import sys
from pathlib import Path

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory


# Verified against SolisClient a72ee470 and the 6.1.1 client descriptors: same
# field number/type, differing only in spelling. No general case-fold fallback.
_MASTER_FIELD_ALIASES = {
    "BacksideQuestSetting": {
        "questCharacterAdvantageId": ("QuestCharacterAdvantageId", 15, 9),
        "questAudienceAdvantageId": ("QuestAudienceAdvantageId", 16, 9),
    },
    "TourQuestSetting": {
        "questCharacterAdvantageId": ("QuestCharacterAdvantageId", 15, 9),
        "questAudienceAdvantageId": ("QuestAudienceAdvantageId", 16, 9),
    },
    "Quest": {
        "questCharacterAdvantageId": ("QuestCharacterAdvantageId", 26, 9),
        "questAudienceAdvantageId": ("QuestAudienceAdvantageId", 27, 9),
    },
    "Music": {"is3DAvailable": ("is3dAvailable", 10, 8)},
    "PhotoExpressionStagePosition": {"lookEffectAssetId": ("LookEffectAssetId", 16, 9)},
    "Setting": {"photoRecipeLimit": ("PhotoRecipeLimit", 113, 3)},
    "ShowcaseSetting": {"showcaseMysetNameLimit": ("ShowcaseMysetNameLimit", 7, 5)},
}


def normalize_master_row(table: str, row, descriptor) -> tuple[dict, int]:
    if not isinstance(row, dict):
        raise ValueError(f"Master row must be an object: {table}")
    result = dict(row)
    changed = 0
    for old, (new, number, kind) in _MASTER_FIELD_ALIASES.get(table, {}).items():
        if old not in result:
            continue
        field = descriptor.fields_by_name.get(new)
        # A schema that already has this exact old field needs no alias.
        if old in descriptor.fields_by_name:
            continue
        if field is None or field.number != number or field.type != kind:
            raise ValueError(f"Verified alias does not match supplied schema: {table}.{old}")
        if new in result or field.json_name in result:
            raise ValueError(f"Conflicting legacy and current field names: {table}.{old}")
        result[new] = result.pop(old)
        changed += 1
    return result, changed



class Schema:
    def __init__(self, pool, files, fingerprint: str | None = None):
        self.pool = pool
        self.files = files
        self.fingerprint = fingerprint or hashlib.sha256(self._serialized()).hexdigest()
        self.methods = {
            f"/{service.full_name}/{method.name}": method
            for file in files
            for service in file.services_by_name.values()
            for method in service.methods
        }
        if "/api.System/Check" not in self.methods:
            raise ValueError("Schema does not contain api.System/Check")
        # upb's native class cache is weak. A GC-cleared dynamic MessageMeta
        # can remain visible there with a NULL descriptor (observed in 7.36.2
        # while resolving FromString). Keep every class, including nested and
        # non-RPC messages, alive for exactly as long as its owning schema.
        self._message_types = {}

        def retain(descriptor):
            self._message_types[descriptor.full_name] = message_factory.GetMessageClass(descriptor)
            for nested in descriptor.nested_types:
                retain(nested)

        for file in files:
            for descriptor in file.message_types_by_name.values():
                retain(descriptor)

    def method(self, path: str):
        try:
            method = self.methods[path]
        except KeyError:
            raise ValueError(f"Unknown RPC method: {path}") from None
        if method.client_streaming or method.server_streaming:
            raise ValueError(f"Streaming RPC is not supported: {path}")
        return method

    def request_type(self, path: str):
        return message_factory.GetMessageClass(self.method(path).input_type)

    def response_type(self, path: str):
        return message_factory.GetMessageClass(self.method(path).output_type)

    @classmethod
    def from_solis(cls, directory: Path):
        directory = Path(directory).resolve(strict=True)
        for name in ("papi_pb2", "ptransaction_pb2", "penum_pb2"):
            if not (directory / (name + ".py")).is_file():
                raise ValueError(f"Missing generated schema: {name}.py")
            existing = sys.modules.get(name)
            if existing and Path(existing.__file__).resolve().parent != directory:
                raise ValueError("Another SolisClient schema is already loaded in this process")
        sys.path.insert(0, str(directory))
        try:
            api = importlib.import_module("papi_pb2")
        finally:
            sys.path.remove(str(directory))
        files = []
        seen = set()

        def visit(file):
            if file.name in seen:
                return
            seen.add(file.name)
            for dependency in file.dependencies:
                visit(dependency)
            files.append(file)

        visit(api.DESCRIPTOR)
        return cls(descriptor_pool.Default(), files)

    @classmethod
    def from_descriptor_set(cls, path: Path):
        raw = path.read_bytes()
        descriptors = descriptor_pb2.FileDescriptorSet.FromString(raw)
        pool = descriptor_pool.DescriptorPool()
        pending = {file.name: file for file in descriptors.file}
        if len(pending) != len(descriptors.file):
            raise ValueError("Descriptor set contains duplicate file names")
        files = []
        while pending:
            progressed = False
            for name, file in list(pending.items()):
                if any(dependency in pending for dependency in file.dependency):
                    continue
                try:
                    pool.Add(file)
                    files.append(pool.FindFileByName(file.name))
                except (TypeError, ValueError) as exc:
                    raise ValueError(f"Cannot load descriptor {name}: {exc}") from None
                del pending[name]
                progressed = True
            if not progressed:
                raise ValueError("Descriptor set has cyclic or missing dependencies")
        return cls(pool, files)

    def _serialized(self):
        descriptors = descriptor_pb2.FileDescriptorSet()
        for file in sorted(self.files, key=lambda file: file.name):
            file.CopyToProto(descriptors.file.add())
        return descriptors.SerializeToString(deterministic=True)

    def export(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self._serialized())
