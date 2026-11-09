"""Version-locked ARM64 bootstrap patches for the user's local 6.1.1 client.

Only the two verified original native binaries are accepted. The local server
ignores Firebase identity; these patches skip Seed/Firebase initialization and
return an already-completed UniTask<string> carrying Api.GetHost's managed URL.
Account.LoginAsync remains intact so the client receives a real local session.
This establishes the patched machine-code contract, not on-device compatibility.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import struct


@dataclass(frozen=True)
class _Site:
    name: str
    rva: int
    offset: int
    expected: str
    action: str


@dataclass(frozen=True)
class _Profile:
    sha256: str
    host_rva: int
    host_offset: int
    host_expected: str
    sites: tuple[_Site, ...]


_PROFILES = {
    "android": _Profile(
        "68d4706d14b33d07647b9752124632a44b6a5901c82723beb569d9123df676b3",
        0x46F4744, 0x46F0744, "fe0f1df8f65701a9f44f02a9f5ca02d0",
        (
            _Site("SeedWrapper.IsInitialized", 0x46BDB28, 0x46B9B28, "fe0f1ef8f44f01a9b4cc02b0b39202d0", "true"),
            _Site("SeedWrapper.SeedId", 0x46BDD4C, 0x46B9D4C, "fe0f1ef8f44f01a9b4cc02b0739202f0", "host"),
            _Site("SeedWrapper.InitializeAsync", 0x46BDEF4, 0x46B9EF4, "ff8302d1fe5f07a9f65708a9f44f09a9", "completed_error"),
            _Site("SeedWrapper.RefreshSeedIdAsync", 0x46BDFD0, 0x46B9FD0, "ff8301d1fe5704a9f44f05a9b5cc02b0", "completed_void"),
            _Site("AccountManager.IsCreatedUser", 0x5054B14, 0x5050B14, "fe0f1ff8e0031faa99a5d9971f0000f1", "true"),
            _Site("AccountManager.GetFirebaseIdTokenAsync", 0x50570B8, 0x50530B8,
                  "ff8302d1fe3b00f9f65708a9f44f09a936800290954802f0f30308aac8b65039", "completed_token"),
        ),
    ),
    "ios": _Profile(
        "b03bee7ede0f8e74c84b3e171f79bc3596e074281b42640eb70bd106474ff5bf",
        0x1E6BCE0, 0x1E6BCE0, "f657bda9f44f01a9fd7b02a9fd830091",
        (
            _Site("SeedWrapper.IsInitialized", 0x1E38F6C, 0x1E38F6C, "f44fbea9fd7b01a9fd430091f45504f0", "true"),
            _Site("SeedWrapper.SeedId", 0x1E3928C, 0x1E3928C, "f44fbea9fd7b01a9fd430091f45504d0", "host"),
            _Site("SeedWrapper.InitializeAsync", 0x1E39480, 0x1E39480, "ff4302d1f85f05a9f65706a9f44f07a9", "completed_error"),
            _Site("SeedWrapper.RefreshSeedIdAsync", 0x1E39560, 0x1E39560, "ffc301d1f65704a9f44f05a9fd7b06a9", "completed_void"),
            _Site("AccountManager.IsCreatedUser", 0x298D8E8, 0x298D8E8, "fd7bbfa9fd030091000080d2d0afd297", "true"),
            _Site("AccountManager.GetFirebaseIdTokenAsync", 0x2990060, 0x2990060,
                  "ff4302d1f85f05a9f65706a9f44f07a9fd7b08a9fd030291f40300aaf30308aa", "completed_token"),
        ),
    ),
}


def _words(*values: int) -> bytes:
    return struct.pack("<" + "I" * len(values), *values)


def _branch(source: int, target: int, *, link: bool = False) -> int:
    displacement = target - source
    if displacement % 4 or not -(1 << 27) <= displacement < (1 << 27):
        raise ValueError("Native bootstrap branch is out of ARM64 range")
    return (0x94000000 if link else 0x14000000) | ((displacement // 4) & 0x3FFFFFF)


def _replacement(site: _Site, host_rva: int) -> bytes:
    if site.action == "true":
        return _words(0x52800020, 0xD65F03C0)  # mov w0, #1; ret
    if site.action == "host":
        return _words(_branch(site.rva, host_rva))
    if site.action == "completed_error":
        # UniTask<Error>: source=null, result=null, token=0; hidden sret x8.
        return _words(0xA9007D1F, 0xF900091F, 0xD65F03C0)
    if site.action == "completed_void":
        # Non-generic UniTask is 16 bytes returned in x0/x1.
        return _words(0xD2800000, 0xD2800001, 0xD65F03C0)
    if site.action == "completed_token":
        # AAPCS64: preserve x19/LR and x8 across GetHost; keep SP 16-aligned.
        # Api.GetHost is static, ignores its MethodInfo argument, and returns an
        # existing managed string. The packager patches its metadata URL first.
        return _words(
            0xA9BF7BF3,  # stp x19, x30, [sp, #-16]!
            0xAA0803F3,  # mov x19, x8
            0xAA1F03E0,  # mov x0, xzr (MethodInfo)
            _branch(site.rva + 12, host_rva, link=True),
            0xA900027F,  # stp xzr, x0, [x19] (source, result)
            0xF9000A7F,  # str xzr, [x19, #16] (token and padding)
            0xA8C17BF3,  # ldp x19, x30, [sp], #16
            0xD65F03C0,
        )
    raise ValueError("Unknown native bootstrap patch action")


def patch_native(native: bytes, platform: str) -> tuple[bytes, dict]:
    """Patch one original 6.1.1 binary without changing its length or layout.

    The native hash and every entry prefix are checked before mutation. Unknown,
    translated, previously patched or other-version binaries are rejected; an
    explicit prepatched-native override belongs to the packaging tool.
    """
    if not isinstance(native, bytes):
        raise ValueError("Native bootstrap input must be bytes")
    if platform not in _PROFILES:
        raise ValueError("Native bootstrap platform must be android or ios")
    profile = _PROFILES[platform]
    source_hash = hashlib.sha256(native).hexdigest()
    if source_hash != profile.sha256:
        raise ValueError("Native bootstrap requires the verified original 6.1.1 binary")
    host_prefix = bytes.fromhex(profile.host_expected)
    if native[profile.host_offset:profile.host_offset + len(host_prefix)] != host_prefix:
        raise ValueError("Native bootstrap Api.GetHost entry does not match its profile")
    changes = []
    for site in profile.sites:
        expected = bytes.fromhex(site.expected)
        if native[site.offset:site.offset + len(expected)] != expected:
            raise ValueError("Native bootstrap entry does not match its profile: " + site.name)
        replacement = _replacement(site, profile.host_rva)
        if len(replacement) > len(expected):
            raise ValueError("Native bootstrap replacement exceeds its verified entry")
        changes.append((site, replacement))
    patched = bytearray(native)
    evidence = []
    for site, replacement in changes:
        patched[site.offset:site.offset + len(replacement)] = replacement
        evidence.append({"method": site.name, "rva": hex(site.rva), "file_offset": hex(site.offset),
                         "action": site.action, "original_hex": native[site.offset:site.offset + len(replacement)].hex(),
                         "patched_hex": replacement.hex()})
    result = bytes(patched)
    return result, {"client_version": "6.1.1", "platform": platform,
                    "input_sha256": source_hash, "output_sha256": hashlib.sha256(result).hexdigest(),
                    "patches": evidence, "device_verified": False,
                    "token": "Api.GetHost managed URL used only as an offline placeholder"}
