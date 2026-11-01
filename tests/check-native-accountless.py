#!/usr/bin/env python3
"""Execute the actual transformed arm64 account routines in an isolated CPU.

Requires unicorn==2.1.4. Imported functions are mocked, so this test never
executes host code from the dylib or creates a network connection.
"""
import importlib.util
from pathlib import Path
import struct
import sys
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
import unicorn.arm64_const as arm

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("account_verifier", ROOT / "scripts/verify-accountless.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
native = verifier.native
source = next(value for name, value in verifier.deb_files(sys.argv[1]).items() if name.endswith("/YTLite.dylib"))
data = native.transform(source)
native.verify(data)
cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
cpu.mem_map(0, 0x2000000)
position = 32
fixups = None
for _ in range(struct.unpack_from("<I", data, 16)[0]):
    command, size = struct.unpack_from("<II", data, position)
    if command == 0x19:
        _, address, _, offset, length = struct.unpack_from("<16sQQQQ", data, position + 8)
        if length:
            cpu.mem_write(address, data[offset:offset + length])
    if command == 0x80000034:
        fixups = struct.unpack_from("<I", data, position + 8)[0]
    position += size
assert fixups is not None
_, starts, imports, strings, count, kind, _ = struct.unpack_from("<7I", data, fixups)
assert kind == 1
symbols = []
for i in range(count):
    value = struct.unpack_from("<I", data, fixups + imports + 4 * i)[0]
    offset = fixups + strings + (value >> 9)
    symbols.append(data[offset:data.index(0, offset)].decode())
external = {}
start = fixups + starts
for i in range(struct.unpack_from("<I", data, start)[0]):
    offset = struct.unpack_from("<I", data, start + 4 + 4 * i)[0]
    if not offset:
        continue
    entry = start + offset
    _, page_size, pointer_format, base, _, pages = struct.unpack_from("<IHHQIH", data, entry)
    assert pointer_format in (2, 6)
    for page in range(pages):
        chain = struct.unpack_from("<H", data, entry + 22 + 2 * page)[0]
        if chain == 0xFFFF:
            continue
        assert chain < 0x8000
        address = base + page * page_size + chain
        while True:
            value = struct.unpack("<Q", cpu.mem_read(address, 8))[0]
            if value >> 63:
                index = value & 0xFFFFFF
                pointer = 0x20000000 + 16 * index
                external[pointer] = symbols[index]
            else:
                pointer = value & ((1 << 36) - 1)
            cpu.mem_write(address, struct.pack("<Q", pointer))
            step = (value >> 51) & 0xFFF
            if not step:
                break
            address += step * 4
cpu.mem_map(0x10000000, 0x200000)
cpu.mem_map(0x20000000, 0x100000)
calls = []
local_bool = 0


def text(address):
    return bytes(cpu.mem_read(address, 128)).split(b"\0")[0].decode()


def imported(_cpu, address, _size, _user):
    symbol = external[address]
    arguments = [cpu.reg_read(getattr(arm, f"UC_ARM64_REG_X{i}")) for i in range(3)]
    calls.append((symbol, arguments))
    if symbol == "_objc_msgSend":
        selector = text(arguments[1])
        if selector == "standardUserDefaults":
            result = 0x10001000
        elif selector == "boolForKey:":
            result = local_bool
        elif selector == "integerForKey:":
            result = 37
        else:
            raise AssertionError(f"Unexpected Objective-C call: {selector}")
    elif symbol.startswith("_objc_retain") or symbol == "_objc_autoreleaseReturnValue":
        result = arguments[0]
    elif symbol in ("_objc_release", "_dispatch_async"):
        result = 0
    else:
        raise AssertionError(f"Unexpected external call: {symbol}")
    cpu.reg_write(arm.UC_ARM64_REG_X0, result)
    cpu.reg_write(arm.UC_ARM64_REG_PC, cpu.reg_read(arm.UC_ARM64_REG_LR))


cpu.hook_add(UC_HOOK_CODE, imported, begin=0x20000000, end=0x200FFFFF)


def run(address, argument=0):
    calls.clear()
    for i in range(31):
        cpu.reg_write(getattr(arm, f"UC_ARM64_REG_X{i}"), 0)
    cpu.reg_write(arm.UC_ARM64_REG_SP, 0x101E0000)
    cpu.reg_write(arm.UC_ARM64_REG_LR, 0x10000000)
    cpu.reg_write(arm.UC_ARM64_REG_X0, argument)
    cpu.emu_start(address, 0x10000000, count=50000)
    assert cpu.reg_read(arm.UC_ARM64_REG_PC) == 0x10000000, "Routine did not return"
    return cpu.reg_read(arm.UC_ARM64_REG_X0)


# Every erased function must return without any external call: no login,
# keychain, device ID, requests, curl, timers, callbacks or blocking reminders.
for patch in native.PROFILE["patches"]:
    if patch.get("kind") == "local_initialization":
        continue
    assert run(patch["offset"]) == patch["return"]
    assert not calls, (patch, calls)

# Local settings keep both enabled/disabled values and integer preferences.
for local_bool in (0, 1):
    assert run(0x238C0, 0x10001100) == local_bool
    assert [text(args[1]) for symbol, args in calls if symbol == "_objc_msgSend"] == ["standardUserDefaults", "boolForKey:"]
assert run(0x23A5C, 0x10001100) == 37
assert [text(args[1]) for symbol, args in calls if symbol == "_objc_msgSend"] == ["standardUserDefaults", "integerForKey:"]

# Crucially, latest SponsorBlock/player hooks must initialize without waiting
# for an account. Verify the original block is scheduled on the real main queue
# import, with normal dispatch_async ownership (not called with the wrong ABI).
run(0x233E8, 0x1061400)
assert len(calls) == 1 and calls[0][0] == "_dispatch_async"
queue, block, _ = calls[0][1]
assert external[queue] == "__dispatch_main_q" and block == 0x1061400
print("PASS: current arm64 account routines erased; local bool/int settings and main-queue tweak initialization work")
