#!/usr/bin/env python3
"""Fail packaging if the background audio patch was omitted or is stale."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import plistlib
import struct
import zipfile


def macho(data):
    if data[:4] == b"\xca\xfe\xba\xbe":
        for i in range(struct.unpack_from(">I", data, 4)[0]):
            cpu, _, offset, size, _ = struct.unpack_from(">5I", data, 8 + i * 20)
            if cpu == 0x100000C:
                return macho(data[offset:offset + size])
        raise ValueError("No arm64 slice found")
    if data[:4] != b"\xcf\xfa\xed\xfe":
        raise ValueError("Expected a 64-bit Mach-O binary")
    _, cpu, _, _, count, size, _, _ = struct.unpack_from("<8I", data)
    if cpu != 0x100000C:
        raise ValueError("Expected an arm64 binary")
    offset, libraries, sections = 32, [], {}
    for _ in range(count):
        cmd, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > 32 + size:
            raise ValueError("Invalid Mach-O load command")
        if cmd in (0xC, 0x80000018):
            name = struct.unpack_from("<I", data, offset + 8)[0]
            libraries.append(data[offset + name:offset + length].split(b"\0")[0].decode())
        if cmd == 0x2C and struct.unpack_from("<I", data, offset + 16)[0]:
            raise ValueError("IPA executable is still encrypted")
        if cmd == 0x19:
            nsections = struct.unpack_from("<I", data, offset + 64)[0]
            for i in range(nsections):
                section = offset + 72 + 80 * i
                name, segment, _, size_bytes, file_offset = struct.unpack_from("<16s16sQQI", data, section)
                key = (segment.rstrip(b"\0").decode(), name.rstrip(b"\0").decode())
                sections[key] = data[file_offset:file_offset + size_bytes]
        offset += length
    return libraries, sections


def verify(ipa, patch):
    expected = Path(patch).read_bytes()
    _, expected_sections = macho(expected)
    patch_name = "YTLBackgroundPlaybackFix.dylib"
    with zipfile.ZipFile(ipa) as archive:
        names = set(archive.namelist())
        apps = [name[:-len("/Info.plist")] for name in names
                if name.startswith("Payload/") and name.endswith(".app/Info.plist")
                and name.count("/") == 2]
        if len(apps) != 1:
            raise ValueError("Expected exactly one main app in Payload")
        app = apps[0]
        info = plistlib.loads(archive.read(app + "/Info.plist"))
        if "audio" not in info.get("UIBackgroundModes", []):
            raise ValueError("Main app is missing the audio background mode")
        executable = info["CFBundleExecutable"]
        if PurePosixPath(executable).name != executable:
            raise ValueError("Invalid app executable name")
        libraries, _ = macho(archive.read(app + "/" + executable))
        injected = [name for name in libraries if PurePosixPath(name).name == patch_name]
        if len(injected) != 1:
            raise ValueError("Main executable must load the background patch exactly once")
        if injected[0] not in ("@rpath/" + patch_name, "@executable_path/Frameworks/" + patch_name):
            raise ValueError("Main executable uses an unresolved path for the background patch")
        path = app + "/Frameworks/" + patch_name
        dependencies, sections = macho(archive.read(path))
        code = sections[("__TEXT", "__text")]
        if code != expected_sections[("__TEXT", "__text")]:
            raise ValueError("Packaged patch does not match the patch built from this branch")
        required = (b"setBackgroundingForcedDisabled:",
                    b"pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:",
                    b"setProhibitsBackgroundAudioPlayback:")
        selectors = sections[("__TEXT", "__objc_methname")].split(b"\0")
        if any(selector not in selectors for selector in required):
            raise ValueError("Packaged patch is missing the v2 screen-lock/PiP guards")
        for name in dependencies:
            if name.startswith("@rpath/"):
                candidates = (app + "/Frameworks/" + name[7:], app + "/" + name[7:])
            elif name.startswith("@loader_path/"):
                candidates = (app + "/Frameworks/" + name[13:],)
            elif name.startswith("@executable_path/"):
                candidates = (app + "/" + name[17:],)
            elif name.startswith(("/System/", "/usr/lib/")):
                continue
            else:
                raise ValueError(f"Unresolved patch dependency: {name}")
            if not any(candidate in names for candidate in candidates):
                raise ValueError(f"Missing patch dependency: {name}")
        print(f"Verified background audio patch in YouTube {info.get('CFBundleShortVersionString')}; "
              f"code SHA-256: {hashlib.sha256(code).hexdigest()}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa")
    parser.add_argument("--patch", required=True)
    arguments = parser.parse_args()
    verify(arguments.ipa, arguments.patch)
