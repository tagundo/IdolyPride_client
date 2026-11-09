"""Create initial local accounts or preserve an exported User.Get response."""

from __future__ import annotations

from pathlib import Path

from google.protobuf.message import DecodeError

from . import codec
from .state import State


_USER_GET = "/api.User/Get"


def import_profile(state: State, schema, profile: str, source: Path, wire: bool = False) -> bytes:
    """Save a validated User.Get snapshot, retaining its exact protobuf bytes.

    ``source`` contains decrypted protobuf, or an application envelope with
    ``wire=True`` (without the five-byte gRPC framing header). Authentication
    requests, metadata and online tokens are not imported. Public account IDs
    are preserved where present; absent IDs retain or receive local identities.
    Return the decrypted snapshot bytes saved to the local database.
    """
    payload = Path(source).read_bytes()
    if wire:
        payload = codec.decode(payload)
    try:
        response = schema.response_type(_USER_GET).FromString(payload)
    except DecodeError as error:
        raise ValueError("Malformed User.Get protobuf snapshot") from error
    if "user" not in response.DESCRIPTOR.fields_by_name or not response.HasField("user") or not response.user.name.strip():
        raise ValueError("User.Get snapshot must contain a user with a nonempty name")
    server_id = public_id = None
    if "userPublic" in response.DESCRIPTOR.fields_by_name and response.HasField("userPublic"):
        server_id = response.userPublic.serverUserId or None
        public_id = response.userPublic.publicUserId or None
    state.save_snapshot(profile, payload, schema.fingerprint, server_id=server_id, public_id=public_id)
    return payload


def new_profile(state: State, schema, profile: str, manager_name: str) -> bytes:
    """Create a minimal initial account and return its User.Get protobuf bytes.

    Only the manager's name, level 1 and local public identity are initialized.
    Cards, unlocked content and cleared tutorials require subsequent handlers;
    this snapshot alone does not establish that the client can enter the home.
    An existing snapshot must be preserved or explicitly replaced by import.
    """
    if not isinstance(manager_name, str) or not manager_name.strip():
        raise ValueError("A nonempty manager name is required")
    if state.snapshot(profile) is not None:
        raise ValueError("This profile already has a snapshot; choose a new profile name")
    response = schema.response_type(_USER_GET)()
    response.user.name = manager_name
    response.user.managerLevel = 1
    identity = state.ensure_profile(profile)
    if "userPublic" in response.DESCRIPTOR.fields_by_name:
        response.userPublic.serverUserId = identity["server_id"]
        response.userPublic.publicUserId = identity["public_id"]
    payload = response.SerializeToString()
    state.save_snapshot(profile, payload, schema.fingerprint)
    return payload
