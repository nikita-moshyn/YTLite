#!/usr/bin/env python3
"""Strip the reviewed current YTPlus account client; reject unknown binaries.

This changes the current release in place, never downloads an older release.
The profile covers its account constructor, login/token/device/keychain/curl
functions, local preference gates, activation reminder, and remote supporter
and donation requests. File offsets and load-command ordinals stay unchanged.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct

PROFILE = json.loads(Path(__file__).with_name("accountless-profile.json").read_text())
NOP = bytes.fromhex("1f2003d5")
RET = bytes.fromhex("c0035fd6")


def sections(data):
    if data[:4] != bytes.fromhex("cffaedfe") or struct.unpack_from("<I", data, 4)[0] != 0x100000C:
        raise ValueError("Account removal requires the reviewed arm64 YTPlus binary")
    count, command_size = struct.unpack_from("<II", data, 16)
    position, result = 32, {}
    for _ in range(count):
        command, size = struct.unpack_from("<II", data, position)
        if size < 8 or position + size > 32 + command_size:
            raise ValueError("Invalid Mach-O command table")
        if command == 0x19:
            for i in range(struct.unpack_from("<I", data, position + 64)[0]):
                name, segment, address, length, offset = struct.unpack_from("<16s16sQQI", data, position + 72 + 80 * i)
                key = segment.rstrip(b"\0").decode() + "," + name.rstrip(b"\0").decode()
                result[key] = (address, offset, length)
        position += size
    if position != 32 + command_size:
        raise ValueError("Invalid Mach-O command table size")
    return result


def replacement(patch):
    # MOV W0, #0/1; RET; NOP padding. Erase the complete original body, not
    # just an entry instruction that leaves callable account callbacks intact.
    size = patch["size"]
    if size < 8 or size % 4:
        raise ValueError("Invalid account removal profile")
    if patch.get("kind") == "local_initialization":
        # Original: queue tweak initializers until remote account verification.
        # Local: dispatch each supplied block directly to the main queue. Keep
        # the original main-queue scheduling and dispatch_async block ownership.
        pc = patch["offset"]
        pages = (0x1060000 - ((pc + 12) & ~0xFFF)) >> 12
        adrp = 0x90000008 | ((pages & 3) << 29) | (((pages >> 2) & 0x7FFFF) << 5)
        branch = 0x94000000 | (((0x3131C - (pc + 20)) >> 2) & 0x3FFFFFF)
        code = struct.pack("<8I", 0xA9BF7BFD, 0x910003FD, 0xAA0003E1,
                           adrp, 0xF9400000 | ((0x760 // 8) << 10) | (8 << 5),
                           branch, 0xA8C17BFD, 0xD65F03C0)
    else:
        code = struct.pack("<I", 0x52800000 | (patch["return"] << 5)) + RET
    return code + NOP * ((size - len(code)) // 4)


def transform(data):
    layout = sections(data)
    # Check code AND its obfuscated jump/string data. A different release must
    # be reviewed, even when its class/method names look compatible.
    for name, expected in PROFILE["sections"].items():
        _, offset, size = layout[name]
        if size != expected["size"] or hashlib.sha256(data[offset:offset + size]).hexdigest() != expected["sha256"]:
            raise ValueError("Unsupported YTPlus binary: account removal profile does not match; no version fallback is allowed")
    result = bytearray(data)
    address, offset, size = layout["__TEXT,__text"]
    for patch in PROFILE["patches"]:
        location = offset + patch["offset"] - address
        if not offset <= location < location + patch["size"] <= offset + size:
            raise ValueError("Account patch is outside executable code")
        result[location:location + patch["size"]] = replacement(patch)
    return bytes(result)


def verify(data):
    layout = sections(data)
    address, offset, size = layout["__TEXT,__text"]
    for patch in PROFILE["patches"]:
        location = offset + patch["offset"] - address
        if data[location:location + patch["size"]] != replacement(patch):
            raise ValueError("YTPlus account client is present or only partially removed")
    digest = hashlib.sha256(data[offset:offset + size]).hexdigest()
    if digest != PROFILE["output_code_sha256"]:
        raise ValueError("Accountless YTPlus code differs from the reviewed build")
    return digest


def sanitize(deb_root):
    root = Path(deb_root)
    binaries = list(root.glob("**/MobileSubstrate/DynamicLibraries/YTLite.dylib"))
    if len(binaries) != 1:
        raise ValueError("Expected one YTLite.dylib in the extracted package")
    binary = binaries[0]
    patched = transform(binary.read_bytes())
    receipt = {"profile": PROFILE["id"], "upstream_version": PROFILE["version"],
               "account_code_removed": True, "code_sha256": verify(patched),
               "blocked_domains": PROFILE["blocked_domains"]}
    bundles = list(root.glob("**/Application Support/YTLite.bundle"))
    if len(bundles) != 1:
        raise ValueError("Expected one YTLite.bundle in the extracted package")
    binary.write_bytes(patched)
    (bundles[0] / "YTLOffline.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted_deb", type=Path)
    args = parser.parse_args()
    print(json.dumps(sanitize(args.extracted_deb), indent=2))
