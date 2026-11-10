"""Dynamic message classes belong to their private Schema, including across GC."""
import gc
import hashlib
import weakref

from google.protobuf import descriptor_pb2, message_factory
import pytest

from idoly_local.schema import Schema


def schema_at(path, *, text=False):
    file = descriptor_pb2.FileDescriptorProto(name="lifetime.proto", package="api", syntax="proto3")
    request = file.message_type.add(name="Request")
    request.field.add(name="value", number=1, label=1, type=9 if text else 5)
    response = file.message_type.add(name="Response")
    entry = response.nested_type.add(name="Entry")
    entry.field.add(name="value", number=1, label=1, type=9 if text else 5)
    response.field.add(name="entry", number=1, label=1, type=11, type_name=".api.Response.Entry")
    unused = file.message_type.add(name="Unused")
    child = unused.nested_type.add(name="Child")
    child.field.add(name="value", number=1, label=1, type=9)
    node = file.message_type.add(name="Node")
    node.field.add(name="children", number=1, label=3, type=11, type_name=".api.Node")
    service = file.service.add(name="System")
    service.method.add(name="Check", input_type=".api.Request", output_type=".api.Response")
    service.method.add(name="Stream", input_type=".api.Request", output_type=".api.Response",
                       server_streaming=True)
    descriptors = descriptor_pb2.FileDescriptorSet()
    descriptors.file.add().CopyFrom(file)
    raw = descriptors.SerializeToString(deterministic=True)
    path.write_bytes(raw)
    return Schema.from_descriptor_set(path), raw


def exercise_private_schemas(tmp_path, iteration):
    schemas = [schema_at(tmp_path / f"{iteration}-{text}.pb", text=text)[0] for text in (False, True)]
    names = ("api.Request", "api.Response", "api.Response.Entry", "api.Unused", "api.Unused.Child", "api.Node")
    references = [
        {name: weakref.ref(message_factory.GetMessageClass(schema.pool.FindMessageTypeByName(name)))
         for name in names}
        for schema in schemas
    ]
    for _ in range(3):
        gc.collect()
        for text, (schema, refs) in enumerate(zip(schemas, references)):
            # No caller holds these classes. Native upb cache entries alone must
            # not decide their lifetime or return a class whose tp_clear ran.
            assert all(ref() is not None for ref in refs.values())
            request_type = schema.request_type("/api.System/Check")
            response_type = schema.response_type("/api.System/Check")
            assert request_type is refs["api.Request"]()
            assert response_type is refs["api.Response"]()
            value = "separate private pool" if text else 37
            assert request_type.FromString(request_type(value=value).SerializeToString()).value == value
            response = response_type()
            response.entry.value = value
            raw = response.SerializeToString() + b"\x80\x4b\x7b"
            assert response_type.FromString(raw).SerializeToString() == raw
            node_type = refs["api.Node"]()
            node = node_type()
            node.children.add().children.add()
            assert node_type.FromString(node.SerializeToString()) == node
    assert references[0]["api.Response"]() is not references[1]["api.Response"]()
    return [weakref.ref(schema) for schema in schemas], references


def test_private_message_classes_survive_gc_and_are_released_with_the_schema(tmp_path):
    for iteration in range(16):
        schema_refs, class_refs = exercise_private_schemas(tmp_path, iteration)
        gc.collect()
        assert all(ref() is None for ref in schema_refs)
        assert all(ref() is None for refs in class_refs for ref in refs.values())


def test_class_retention_preserves_schema_fingerprint_export_and_method_errors(tmp_path):
    schema, raw = schema_at(tmp_path / "input.pb")
    assert schema.fingerprint == hashlib.sha256(raw).hexdigest()
    schema.export(tmp_path / "export.pb")
    assert (tmp_path / "export.pb").read_bytes() == raw
    with pytest.raises(ValueError, match="Unknown RPC method"):
        schema.request_type("/api.System/Missing")
    with pytest.raises(ValueError, match="Streaming RPC"):
        schema.response_type("/api.System/Stream")
