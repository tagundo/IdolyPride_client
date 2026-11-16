"""Actual descriptor construction, byte identity and isolated startup reuse."""
import os
from pathlib import Path

from google.protobuf import descriptor_pb2
from google.protobuf.message import DecodeError
import pytest

from idoly_local import startup_cache
from idoly_local.schema import Schema


def descriptor(path, *, name="Empty"):
    file=descriptor_pb2.FileDescriptorProto(name="startup.proto",package="api",syntax="proto3")
    file.message_type.add(name=name)
    file.service.add(name="System").method.add(name="Check",input_type=".api."+name,output_type=".api."+name)
    bundle=descriptor_pb2.FileDescriptorSet();bundle.file.add().CopyFrom(file)
    path.write_bytes(bundle.SerializeToString(deterministic=True))
    return path


@pytest.fixture(autouse=True)
def clean_process_cache():
    startup_cache._SCHEMA_CACHE.clear()
    yield
    startup_cache._SCHEMA_CACHE.clear()


def test_exact_descriptor_build_is_reused_but_per_runtime_metadata_is_isolated(tmp_path,monkeypatch):
    path=descriptor(tmp_path/"schema.pb")
    parser=Schema.from_descriptor_set.__func__;calls=[]
    def count(cls,source):
        calls.append(source.read_bytes());return parser(cls,source)
    monkeypatch.setattr(Schema,"from_descriptor_set",classmethod(count))
    first=startup_cache.load_startup_schema(path)
    first.methods.clear();first.files.clear();first._message_types.clear()
    second=startup_cache.load_startup_schema(path)
    assert len(calls)==1 and first is not second and first.pool is second.pool
    assert second.method("/api.System/Check") and second.files and second._message_types
    message=second.request_type("/api.System/Check")()
    assert message.SerializeToString()==b""


def test_changed_descriptor_content_rebuilds_even_with_restored_modification_time(tmp_path,monkeypatch):
    path=descriptor(tmp_path/"schema.pb");old=path.stat()
    first=startup_cache.load_startup_schema(path)
    descriptor(path,name="Other");os.utime(path,ns=(old.st_atime_ns,old.st_mtime_ns))
    second=startup_cache.load_startup_schema(path)
    assert first.fingerprint!=second.fingerprint and first.pool is not second.pool
    path.write_bytes(b"not protobuf")
    with pytest.raises((DecodeError,ValueError)):startup_cache.load_startup_schema(path)


@pytest.mark.parametrize("damage",["missing","symlink","hardlink","directory","empty","oversize"])
def test_schema_cache_never_authorizes_an_unsafe_or_missing_source(tmp_path,monkeypatch,damage):
    path=descriptor(tmp_path/"schema.pb");startup_cache.load_startup_schema(path)
    if damage=="missing":path.unlink()
    elif damage=="symlink":
        actual=tmp_path/"actual.pb";path.rename(actual);path.symlink_to(actual)
    elif damage=="hardlink":os.link(path,tmp_path/"other.pb")
    elif damage=="directory":path.unlink();path.mkdir()
    elif damage=="empty":path.write_bytes(b"")
    elif damage=="oversize":monkeypatch.setattr(startup_cache,"_MAX_DESCRIPTOR",path.stat().st_size-1)
    with pytest.raises((OSError,ValueError)):startup_cache.load_startup_schema(path)


def test_descriptor_cache_retains_only_one_validated_pool(tmp_path):
    for number in range(4):
        startup_cache.load_startup_schema(descriptor(tmp_path/str(number),name="Empty"+str(number)))
        assert len(startup_cache._SCHEMA_CACHE)==1
