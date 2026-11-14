"""Bounded, platform-aware input checks shared by the iOS-only build tools."""
from __future__ import annotations
import hashlib
import os
import plistlib
from pathlib import Path, PurePosixPath
import stat
import struct

CHUNK = 64 * 1024
MAX_COMMANDS = 1024 * 1024
ARM64, X86_64 = 0x0100000C, 0x01000007
PLATFORMS = {'device': 2, 'simulator': 7}

def require(value, message):
    if not value:
        raise ValueError(message)

def safe_name(name):
    require(isinstance(name, str) and 0 < len(name.encode('utf-8')) <= 1024 and '\\' not in name and '\0' not in name, 'Unsafe archive path')
    value = PurePosixPath(name)
    require(not value.is_absolute() and str(value) == name and all(p not in ('', '.', '..') for p in value.parts), 'Unsafe archive path')
    return value

def regular(path):
    path = Path(path)
    info = path.lstat()
    require(not path.is_symlink() and stat.S_ISREG(info.st_mode), 'Regular non-symlink input required')
    return info

def stamp(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns

def sha_file(path, maximum=None):
    before = regular(path)
    require(maximum is None or before.st_size <= maximum, 'Input exceeds size bound')
    h = hashlib.sha256()
    with Path(path).open('rb') as incoming:
        for block in iter(lambda: incoming.read(CHUNK), b''):
            h.update(block)
    require(stamp(before) == stamp(regular(path)), 'Input changed during hashing')
    return h.hexdigest()

def verify_file(path, row):
    require(regular(path).st_size == row['bytes'] and sha_file(path, row['bytes']) == row['sha256'], 'Pinned input size/SHA differs')

def stream_copy(incoming, outgoing, expected_bytes, expected_sha256=None):
    h = hashlib.sha256(); count = 0
    while block := incoming.read(CHUNK):
        require(isinstance(block, bytes) and len(block) <= CHUNK, 'Input read exceeded streaming chunk bound')
        count += len(block)
        require(count <= expected_bytes, 'Member exceeds expected size')
        require(outgoing.write(block) == len(block), 'Short destination write')
        h.update(block)
    require(count == expected_bytes and (expected_sha256 is None or h.hexdigest() == expected_sha256), 'Member size/SHA differs')
    return h.hexdigest()

def _cstring(data, start, end):
    require(0 <= start < end <= len(data), 'Malformed Mach-O string offset')
    stop = data.find(b'\0', start, end)
    require(stop >= start, 'Unterminated Mach-O string')
    try:
        return data[start:stop].decode('ascii')
    except UnicodeError:
        raise ValueError('Non-ASCII Mach-O path') from None

def _slice(stream, offset, size, target, expected_cpu=None):
    require(size >= 32, 'Truncated Mach-O header')
    stream.seek(offset); header = stream.read(32)
    require(len(header) == 32 and header[:4] == b'\xcf\xfa\xed\xfe', 'Expected thin little-endian 64-bit Mach-O')
    _, cpu, subtype, kind, count, command_size, flags, reserved = struct.unpack('<8I', header)
    require(cpu in (ARM64, X86_64) and (expected_cpu is None or cpu == expected_cpu), 'Wrong Mach-O architecture')
    require(kind in (2, 6) and 0 < count <= 8192 and 0 < command_size <= min(MAX_COMMANDS, size - 32), 'Malformed Mach-O load commands')
    commands = stream.read(command_size); require(len(commands) == command_size, 'Truncated Mach-O commands')
    cursor = 0; builds = []; dependencies = []; rpaths = []; identifier = None; signature = False
    for _ in range(count):
        require(cursor + 8 <= command_size, 'Truncated Mach-O command')
        command, length = struct.unpack_from('<II', commands, cursor)
        require(length >= 8 and length % 8 == 0 and cursor + length <= command_size, 'Malformed Mach-O command size')
        if command == 0x32:
            require(length >= 24, 'Malformed LC_BUILD_VERSION')
            platform, minimum, sdk, tools = struct.unpack_from('<4I', commands, cursor + 8)
            require(length == 24 + tools * 8, 'Malformed build-version tool table')
            builds.append({'platform': platform, 'minimum': minimum, 'sdk': sdk})
        elif command in (0xC, 0xD, 0x80000018, 0x8000001F, 0x80000023):
            require(length >= 24, 'Malformed dylib command')
            relative = struct.unpack_from('<I', commands, cursor + 8)[0]
            require(24 <= relative < length, 'Malformed dylib command path')
            name = _cstring(commands, cursor + relative, cursor + length)
            if command == 0xD:
                require(identifier is None, 'Duplicate dylib identity'); identifier = name
            else:
                dependencies.append(name)
        elif command == 0x8000001C:
            require(length >= 16, 'Malformed rpath command')
            relative = struct.unpack_from('<I', commands, cursor + 8)[0]
            require(12 <= relative < length, 'Malformed rpath offset')
            rpaths.append(_cstring(commands, cursor + relative, cursor + length))
        elif command == 0x1D:
            require(length >= 16, 'Malformed code signature command')
            location, amount = struct.unpack_from('<II', commands, cursor + 8)
            require(0 < amount and location + amount <= size, 'Code signature outside Mach-O slice')
            signature = True
        elif command in (0x21, 0x2C):
            require(length >= 24 and struct.unpack_from('<I', commands, cursor + 16)[0] == 0, 'Encrypted Mach-O input')
        cursor += length
    require(cursor == command_size and len(builds) == 1 and builds[0]['platform'] == PLATFORMS[target], 'Mach-O platform differs from requested iOS target')
    return {'cpu': cpu, 'architecture': 'arm64' if cpu == ARM64 else 'x86_64', 'filetype': kind, 'build_version': builds[0], 'dependencies': dependencies, 'rpaths': rpaths, 'install_name': identifier, 'code_signature_command': signature}

def audit_macho(path, target, *, require_signature=False, maximum=128 * 1024**2):
    require(target in PLATFORMS, 'Unknown iOS target')
    before = regular(path); require(0 < before.st_size <= maximum, 'Native framework exceeds bound')
    with Path(path).open('rb') as source:
        magic = source.read(8); slices = []
        if magic[:4] == b'\xcf\xfa\xed\xfe':
            slices.append(_slice(source, 0, before.st_size, target))
        else:
            require(magic[:4] in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'), 'Expected Mach-O framework')
            count = struct.unpack('>I', magic[4:])[0]; require(0 < count <= 8, 'Malformed universal framework')
            width = 32 if magic[:4] == b'\xca\xfe\xba\xbf' else 20
            table = source.read(count * width); require(len(table) == count * width, 'Truncated universal table')
            ranges = []; cpus = set()
            for n in range(count):
                if width == 32:
                    cpu, subtype, offset, size, align, reserved = struct.unpack_from('>IIQQII', table, n * width)
                else:
                    cpu, subtype, offset, size, align = struct.unpack_from('>5I', table, n * width)
                require(cpu not in cpus and 0 <= align <= 30 and offset >= 8 + count * width and offset % (1 << align) == 0 and size >= 32 and offset + size <= before.st_size, 'Malformed universal slice')
                require(not any(max(offset, lo) < min(offset + size, hi) for lo, hi in ranges), 'Overlapping universal slices')
                ranges.append((offset, offset + size)); cpus.add(cpu); slices.append(_slice(source, offset, size, target, cpu))
    require(target != 'device' or [s['cpu'] for s in slices] == [ARM64], 'Device frameworks must contain only arm64')
    require(not require_signature or all(s['code_signature_command'] for s in slices), 'Unsigned framework binary')
    require(stamp(before) == stamp(regular(path)), 'Native framework changed during audit')
    return {'bytes': before.st_size, 'sha256': sha_file(path), 'target': target, 'slices': slices}

def audit_frameworks(frameworks, target, *, require_signature=True):
    root = Path(frameworks); inventory = {}; binaries = {}
    for framework in sorted(root.glob('*.framework')):
        require(framework.is_dir() and not framework.is_symlink(), 'Framework must be a real directory')
        name = framework.stem; binary = framework / name
        require(regular(framework / 'Info.plist').st_size <= 128 * 1024, 'Framework Info.plist exceeds bound')
        info = plistlib.loads((framework / 'Info.plist').read_bytes())
        require(info.get('CFBundleExecutable') == name and info.get('CFBundlePackageType') == 'FMWK', 'Framework metadata/executable differs')
        require(info.get('CFBundleSupportedPlatforms') == ['iPhoneOS' if target == 'device' else 'iPhoneSimulator'], 'Framework Info.plist platform differs')
        require(binary.is_file(), 'Framework executable missing')
        binaries[name] = binary
        inventory[name] = audit_macho(binary, target, require_signature=require_signature)
    require('Python' in inventory, 'Python framework missing')
    for name, report in inventory.items():
        for item in report['slices']:
            require(item['filetype'] == 6 and item['install_name'] == '@rpath/' + name + '.framework/' + name, 'Framework dylib identity differs')
            for dependency in item['dependencies']:
                if dependency.startswith(('/usr/lib/', '/System/Library/Frameworks/')):
                    continue
                if dependency.startswith('@rpath/'):
                    relative = safe_name(dependency.removeprefix('@rpath/'))
                    require(len(relative.parts) == 2 and relative.parts[0].endswith('.framework') and relative.parts[0][:-10] == relative.parts[1] and relative.parts[1] in binaries, 'Unresolved framework dependency')
                else:
                    raise ValueError('Native dependency is not an iOS system library or bundled framework')
    return inventory
