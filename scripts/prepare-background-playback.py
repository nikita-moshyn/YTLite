#!/usr/bin/env python3
"""Remove a previous background patch from a staged IPA before reinjection."""
import argparse
from pathlib import PurePosixPath
import plistlib
import struct
import zipfile

PATCH_NAME = "YTLBackgroundPlaybackFix.dylib"


def remove_patch_loads(data):
    result = bytearray(data)
    if data[:4] == b"\xca\xfe\xba\xbe":
        for index in range(struct.unpack_from(">I", data, 4)[0]):
            cpu, _, offset, size, _ = struct.unpack_from(">5I", data, 8 + 20 * index)
            if cpu == 0x100000C:
                result[offset:offset + size] = remove_patch_loads(data[offset:offset + size])
        return bytes(result)
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected an arm64 Mach-O executable")
    count, size = struct.unpack_from("<II", data, 16)
    offset = 32
    for _ in range(count):
        cmd, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > 32 + size:
            raise ValueError("Invalid executable load command")
        drop = False
        if cmd in (0xC, 0x80000018):
            start = struct.unpack_from("<I", data, offset + 8)[0]
            name = data[offset + start:offset + length].split(b"\0")[0].decode()
            drop = PurePosixPath(name).name == PATCH_NAME
        if drop:
            # Do not delete a dependency command: that renumbers subsequent
            # dylib ordinals used by the executable's existing symbol bindings.
            # Replace this injected-only dependency with the already loaded
            # system library, preserving every ordinal and file offset. Cyan
            # will append a fresh command for the new background patch.
            name = b"/usr/lib/libSystem.B.dylib\0"
            replacement = struct.pack("<6I", cmd, length, 24, 0, 0, 0) + name
            if len(replacement) > length:
                raise ValueError("Not enough room to replace the old patch dependency")
            result[offset:offset + length] = replacement + bytes(length - len(replacement))
        offset += length
    if offset != 32 + size:
        raise ValueError("Invalid executable command table size")
    return bytes(result)


def prepare(source, destination):
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
        main = remove_patch_loads(archive.read(executable))
        # Keep file offsets unchanged; Cyan removes the old code signature and
        # injects the freshly built library after this staged copy is prepared.
        with zipfile.ZipFile(destination, "w") as output:
            for entry in archive.infolist():
                if entry.filename == app + "Frameworks/" + PATCH_NAME:
                    continue
                data = main if entry.filename == executable else archive.read(entry)
                output.writestr(entry, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    prepare(args.source, args.destination)
