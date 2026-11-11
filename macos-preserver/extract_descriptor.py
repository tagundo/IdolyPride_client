#!/usr/bin/env python3
"""Extract one pinned public protocol descriptor, never the full server payload."""
import argparse
import hashlib
from pathlib import Path
from zipfile import ZipFile

PAYLOAD_SHA256 = "3139ea69af1305a231ca09a3caab88a4496f1663c7a3af30892c588ed2cbc436"
DESCRIPTOR_SHA256 = "c82cee62abdca7144d11e710a6f773211464a89d2ddede207999a0a5e7aec8ad"
MEMBER = "data/protocol/idolypride-6.1.1.pb"


def extract(payload: Path, output: Path):
    with payload.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != PAYLOAD_SHA256:
            raise ValueError("pinned_public_payload_mismatch")
    with ZipFile(payload) as archive:
        if archive.namelist().count(MEMBER) != 1:
            raise ValueError("pinned_descriptor_member_invalid")
        info = archive.getinfo(MEMBER)
        if not 0 < info.file_size <= 32 * 1024 * 1024:
            raise ValueError("pinned_descriptor_member_invalid")
        raw = archive.read(info)
    if hashlib.sha256(raw).hexdigest() != DESCRIPTOR_SHA256:
        raise ValueError("pinned_descriptor_mismatch")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as stream:
        stream.write(raw)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    extract(args.payload, args.output)
