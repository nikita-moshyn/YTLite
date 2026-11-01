#!/usr/bin/env python3
"""Fail packaging if the current account client or privacy patch is missing."""
import argparse
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import plistlib
import struct
import tarfile
import zipfile


def module(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


native = module("remove-account")
macho = module("verify-background-playback").macho
PATCH = "YTLAccountless.dylib"


def deb_files(path):
    data = Path(path).read_bytes()
    if data[:8] != b"!<arch>\n":
        raise ValueError("Expected a Debian archive")
    position = 8
    while position < len(data):
        header = data[position:position + 60]
        if len(header) != 60 or header[58:] != b"`\n":
            raise ValueError("Invalid Debian archive member")
        name = header[:16].decode().strip().rstrip("/")
        size = int(header[48:58])
        start = position + 60
        if start + size > len(data):
            raise ValueError("Truncated Debian archive")
        if name.startswith("data.tar"):
            with tarfile.open(fileobj=io.BytesIO(data[start:start + size]), mode="r:*") as archive:
                return {entry.name.removeprefix("./"): archive.extractfile(entry).read()
                        for entry in archive.getmembers() if entry.isfile()
                        and (entry.name.endswith("/YTLite.dylib") or entry.name.endswith("/YTLOffline.json"))}
        position = start + size + size % 2
    raise ValueError("Debian archive is missing its data member")


def verify_native(files):
    binaries = [value for name, value in files.items() if name.endswith("/YTLite.dylib")]
    receipts = [value for name, value in files.items() if name.endswith("/YTLite.bundle/YTLOffline.json")]
    if len(binaries) != 1 or len(receipts) != 1:
        raise ValueError("Missing sanitized YTLite binary or account removal receipt")
    digest = native.verify(binaries[0])
    receipt = json.loads(receipts[0])
    if (receipt.get("profile") != native.PROFILE["id"] or receipt.get("code_sha256") != digest
            or receipt.get("account_code_removed") is not True):
        raise ValueError("Account removal receipt does not match the reviewed binary")
    return receipt


def verify(ipa, patch):
    _, expected = macho(Path(patch).read_bytes())
    with zipfile.ZipFile(ipa) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or archive.testzip():
            raise ValueError("IPA contains duplicate or damaged ZIP entries")
        plists = [name for name in names if name.startswith("Payload/")
                  and name.endswith(".app/Info.plist") and name.count("/") == 2]
        if len(plists) != 1:
            raise ValueError("Expected one main app")
        app = plists[0][:-len("Info.plist")]
        info = plistlib.loads(archive.read(plists[0]))
        executable = info["CFBundleExecutable"]
        if PurePosixPath(executable).name != executable:
            raise ValueError("Invalid app executable name")
        libraries, _ = macho(archive.read(app + executable))
        for name in (PATCH, "YTLite.dylib"):
            linked = [library for library in libraries if PurePosixPath(library).name == name]
            if len(linked) != 1 or linked[0] not in ("@rpath/" + name, "@executable_path/Frameworks/" + name):
                raise ValueError(f"Main executable must load {name} exactly once from Frameworks")
        receipt = verify_native({name: archive.read(name) for name in names
                                 if name.endswith(("/YTLite.dylib", "/YTLite.bundle/YTLOffline.json"))})
        dependencies, actual = macho(archive.read(app + "Frameworks/" + PATCH))
        for key in (("__TEXT", "__text"), ("__TEXT", "__cstring"), ("__TEXT", "__objc_methname")):
            if actual.get(key) != expected.get(key) or key not in actual:
                raise ValueError("Account privacy patch does not match this branch")
        for dependency in dependencies:
            if dependency.startswith(("/usr/lib/", "/System/")):
                continue
            prefix = next((prefix for prefix in ("@rpath/", "@loader_path/", "@executable_path/")
                           if dependency.startswith(prefix)), None)
            target = app + ("" if prefix == "@executable_path/" else "Frameworks/") + dependency[len(prefix or ""):]
            if not prefix or target not in names:
                raise ValueError(f"Unresolved account privacy dependency: {dependency}")
        # The earlier crash occurred before any tweak loaded. Reject duplicates
        # in every arm64 image/slice, not only the two newly injected libraries.
        images = 0
        for name in names:
            if name.endswith("/"):
                continue
            with archive.open(name) as stream:
                magic = stream.read(4)
            if magic not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                continue
            data = archive.read(name)
            if magic == b"\xca\xfe\xba\xbe":
                for i in range(struct.unpack_from(">I", data, 4)[0]):
                    cpu, _, offset, size, _ = struct.unpack_from(">5I", data, 8 + 20 * i)
                    if cpu == 0x100000C:
                        macho(data[offset:offset + size])
            else:
                macho(data)
            images += 1
    result = {"upstream_version": receipt["upstream_version"], "profile": receipt["profile"],
              "account_code_removed": True, "privacy_patch_verified": True, "macho_images": images,
              "device_launch_tested": False, "device_network_capture_tested": False}
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ipa", nargs="?")
    parser.add_argument("--patch")
    parser.add_argument("--deb", type=Path)
    args = parser.parse_args()
    if args.deb:
        print(json.dumps(verify_native(deb_files(args.deb)), indent=2))
    elif args.ipa and args.patch:
        verify(args.ipa, args.patch)
    else:
        parser.error("supply --deb or IPA --patch DYLIB")
