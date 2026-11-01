#!/usr/bin/env python3
"""Remove a previous background patch from a staged IPA before reinjection."""
import argparse
from pathlib import PurePosixPath
import plistlib
import struct
import zipfile

PATCH_NAME = "YTLBackgroundPlaybackFix.dylib"
REPLACED = (PATCH_NAME, "YTLAccountless.dylib", "YTLite.dylib")
DEPENDENCIES = (0xC, 0x80000018, 0x8000001F, 0x80000023, 0x20)


def highest_imported_ordinal(data, commands):
    highest = 0
    for command, offset, _ in commands:
        if command == 0x80000034:
            fixups, length = struct.unpack_from("<II", data, offset + 8)
            if fixups + length > len(data) or length < 28:
                raise ValueError("Invalid chained fixups")
            _, _, imports, _, count, kind, _ = struct.unpack_from("<7I", data, fixups)
            stride = {1: 4, 2: 8, 3: 16}.get(kind)
            if stride is None or imports + count * stride > length:
                raise ValueError("Unsupported chained imports")
            for i in range(count):
                value = struct.unpack_from("<Q" if kind == 3 else "<I", data, fixups + imports + i * stride)[0]
                ordinal = value & (0xFFFF if kind == 3 else 0xFF)
                if ordinal < (0xFFF0 if kind == 3 else 0xF0):
                    highest = max(highest, ordinal)
        elif command in (0x22, 0x80000022):
            fields = struct.unpack_from("<12I", data, offset)
            if any(fields[i] for i in (5, 7, 9)):
                raise ValueError("Legacy symbol bindings: use a clean original IPA")
        elif command == 0x2:
            symbols, count = struct.unpack_from("<II", data, offset + 8)
            if symbols + count * 16 > len(data):
                raise ValueError("Invalid symbol table")
            for i in range(count):
                _, kind, _, desc, _ = struct.unpack_from("<IBBHQ", data, symbols + i * 16)
                if kind & 0xE == 0 and kind & 1 and desc >> 8 < 0xF0:
                    highest = max(highest, desc >> 8)
    return highest


def remove_patch_loads(data, replaced=(PATCH_NAME,)):
    result = bytearray(data)
    if data[:4] == b"\xca\xfe\xba\xbe":
        for index in range(struct.unpack_from(">I", data, 4)[0]):
            cpu, _, offset, size, _ = struct.unpack_from(">5I", data, 8 + 20 * index)
            if cpu == 0x100000C:
                result[offset:offset + size] = remove_patch_loads(data[offset:offset + size], replaced)
        return bytes(result)
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected an arm64 Mach-O executable")
    count, size = struct.unpack_from("<II", data, 16)
    offset, ordinal, seen, commands, retained, dropped = 32, 0, set(), [], [], []
    for _ in range(count):
        cmd, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > 32 + size:
            raise ValueError("Invalid executable load command")
        drop = False
        commands.append((cmd, offset, length))
        if cmd in DEPENDENCIES:
            ordinal += 1
            start = struct.unpack_from("<I", data, offset + 8)[0]
            if not 24 <= start < length:
                raise ValueError("Invalid dylib name")
            name = data[offset + start:offset + length].split(b"\0")[0].decode()
            drop = PurePosixPath(name).name in replaced or name in seen
            seen.add(name)
        if drop:
            dropped.append(ordinal)
        else:
            retained.append(data[offset:offset + length])
        offset += length
    if offset != 32 + size:
        raise ValueError("Invalid executable command table size")
    if dropped:
        if min(dropped) <= highest_imported_ordinal(data, commands):
            raise ValueError("Removing this dependency would renumber live symbol bindings; use a clean IPA")
        compacted = b"".join(retained)
        result[32:32 + size] = compacted + bytes(size - len(compacted))
        struct.pack_into("<II", result, 16, len(retained), len(compacted))
    return bytes(result)


def prepare(source, destination, replace_ytlite=False):
    with zipfile.ZipFile(source) as archive:
        plists = [name for name in archive.namelist() if name.startswith("Payload/")
                  and name.endswith(".app/Info.plist") and name.count("/") == 2]
        if len(plists) != 1:
            raise ValueError("Expected one main app in the IPA")
        app = plists[0][:-len("Info.plist")]
        info = plistlib.loads(archive.read(plists[0]))
        name = info["CFBundleExecutable"]
        if PurePosixPath(name).name != name:
            raise ValueError("Invalid executable name")
        executable = app + name
        replaced = REPLACED if replace_ytlite else (PATCH_NAME,)
        main = remove_patch_loads(archive.read(executable), replaced)
        # Keep file offsets unchanged; Cyan removes the old code signature and
        # injects the freshly built library after this staged copy is prepared.
        with zipfile.ZipFile(destination, "w") as output:
            for entry in archive.infolist():
                if entry.filename in {app + "Frameworks/" + name for name in replaced}:
                    continue
                data = main if entry.filename == executable else archive.read(entry)
                output.writestr(entry, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--replace-ytlite", action="store_true")
    args = parser.parse_args()
    prepare(args.source, args.destination, args.replace_ytlite)
