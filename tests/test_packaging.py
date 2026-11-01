import contextlib
from email.message import Message
import importlib.util
import io
import os
from pathlib import Path
import plistlib
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PATCH_NAME = "YTLBackgroundPlaybackFix.dylib"
SELECTORS = (b"setBackgroundingForcedDisabled:\0"
             b"pictureInPictureControllerShouldProhibitBackgroundAudioPlayback:\0"
             b"setProhibitsBackgroundAudioPlayback:\0")


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


download = load("download-extra-tweaks")
verify = load("verify-background-playback")
prepare = load("prepare-background-playback")


def binary(libraries=(), code=None, selectors=SELECTORS):
    commands = b""
    for library in libraries:
        name = library.encode() + b"\0"
        size = (24 + len(name) + 7) & ~7
        commands += struct.pack("<6I", 0xC, size, 24, 0, 0, 0) + name + bytes(size - 24 - len(name))
    if code is not None:
        start = 32 + len(commands) + 72 + 2 * 80
        segment = struct.pack("<II16s4Q4I", 0x19, 232, b"__TEXT", 0, start + len(code) + len(selectors),
                              0, start + len(code) + len(selectors), 7, 5, 2, 0)
        for name, offset, size in ((b"__text", start, len(code)),
                                   (b"__objc_methname", start + len(code), len(selectors))):
            segment += struct.pack("<16s16sQQ8I", name, b"__TEXT", offset, size, offset, 0, 0, 0, 0, 0, 0, 0)
        commands += segment
    header = struct.pack("<8I", 0xFEEDFACF, 0x100000C, 0, 6, len(libraries) + (code is not None), len(commands), 0, 0)
    return header + commands + ((code + selectors) if code is not None else b"")


class PackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.expected = binary(("@rpath/YTLite.dylib",), b"current patch instructions")
        self.patch_file = self.root / PATCH_NAME
        self.patch_file.write_bytes(self.expected)

    def ipa(self, *, injected=None, modes=("audio",), packaged=None, dependency=True):
        if injected is None:
            injected = ("@rpath/" + PATCH_NAME,)
        path = self.root / "app.ipa"
        with zipfile.ZipFile(path, "w") as archive:
            app = "Payload/YouTube.app/"
            archive.writestr(app + "Info.plist", plistlib.dumps({
                "CFBundleExecutable": "YouTube", "UIBackgroundModes": list(modes),
                "CFBundleShortVersionString": "21.43.5"}))
            archive.writestr(app + "YouTube", binary(injected))
            archive.writestr(app + "Frameworks/" + PATCH_NAME, self.expected if packaged is None else packaged)
            if dependency:
                archive.writestr(app + "Frameworks/YTLite.dylib", binary())
        return path

    def test_final_ipa_contains_current_patch(self):
        with contextlib.redirect_stdout(io.StringIO()):
            verify.verify(self.ipa(), self.patch_file)

    def test_missing_or_duplicate_injection_is_rejected(self):
        for libraries in ((), ("@rpath/" + PATCH_NAME,) * 2):
            with self.subTest(libraries=libraries), self.assertRaisesRegex(ValueError, "exactly once|duplicate linked"):
                verify.verify(self.ipa(injected=libraries), self.patch_file)

    def test_stale_patch_is_rejected(self):
        old = binary(("@rpath/YTLite.dylib",), b"previous patch instructions")
        with self.assertRaisesRegex(ValueError, "does not match"):
            verify.verify(self.ipa(packaged=old), self.patch_file)

    def test_missing_guards_are_rejected_even_with_matching_code(self):
        old = binary(("@rpath/YTLite.dylib",), b"previous code", b"isPlayableInBackground\0")
        self.patch_file.write_bytes(old)
        with self.assertRaisesRegex(ValueError, "missing the v2"):
            verify.verify(self.ipa(packaged=old), self.patch_file)

    def test_missing_background_mode_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "audio background mode"):
            verify.verify(self.ipa(modes=("fetch",)), self.patch_file)

    def test_missing_dependency_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing patch dependency"):
            verify.verify(self.ipa(dependency=False), self.patch_file)

    def test_unresolved_main_load_path_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "unresolved path"):
            verify.verify(self.ipa(injected=("/missing/" + PATCH_NAME,)), self.patch_file)

    def test_previous_patch_is_removed_without_changing_other_loads(self):
        original = binary(("@rpath/" + PATCH_NAME, "@rpath/YTLite.dylib", "@rpath/" + PATCH_NAME), b"unchanged code")
        cleaned = prepare.remove_patch_loads(original)
        libraries, sections = verify.macho(cleaned)
        self.assertEqual(libraries, ["@rpath/YTLite.dylib"])
        self.assertEqual(sections[("__TEXT", "__text")], b"unchanged code")
        self.assertEqual(len(cleaned), len(original))

    def test_staging_removes_old_binary_and_all_old_patch_loads(self):
        source = self.ipa(injected=("@rpath/" + PATCH_NAME,) * 2)
        destination = self.root / "prepared.ipa"
        prepare.prepare(source, destination)
        with zipfile.ZipFile(destination) as archive:
            self.assertNotIn("Payload/YouTube.app/Frameworks/" + PATCH_NAME, archive.namelist())
            self.assertEqual(verify.macho(archive.read("Payload/YouTube.app/YouTube"))[0], [])
        with zipfile.ZipFile(source) as archive:
            self.assertIn("Payload/YouTube.app/Frameworks/" + PATCH_NAME, archive.namelist())

    def test_cyan_receives_files_once_with_spaces_preserved(self):
        (self.root / "ytplus.deb").touch()
        (self.root / "Extra audio.deb").touch()
        (self.root / "YTLAccountless.dylib").touch()
        (self.root / "OpenYoutubeSafariExtension.appex").mkdir()
        fake = self.root / "cyan"
        fake.write_text('#!/bin/bash\nprintf "%s\\0" "$@" > "$ARGS_FILE"\n')
        fake.chmod(0o755)
        # Substitute the external verifier only for this shell-argument unit
        # test. Real sanitization/injection are tested against the actual DEB.
        python = self.root / "python3"
        python.write_text('#!/bin/bash\nif [[ "$1" == *verify-accountless.py ]]; then exit 0; fi\nexec '
                          + __import__('shlex').quote(sys.executable) + ' "$@"\n')
        python.chmod(0o755)
        captured = self.root / "arguments"
        environment = dict(os.environ, PATH=str(self.root) + os.pathsep + os.environ["PATH"],
                           ARGS_FILE=str(captured), REQUIRE_BACKGROUND_FIX="true")
        subprocess.run([str(ROOT / "scripts/inject-tweaks.sh"), str(self.ipa()), "output.ipa", "My YouTube", "test.app"],
                       cwd=self.root, env=environment, check=True)
        args = captured.read_bytes().split(b"\0")[:-1]
        for name in (b"ytplus.deb", PATCH_NAME.encode(), b"YTLAccountless.dylib", b"Extra audio.deb", b"OpenYoutubeSafariExtension.appex"):
            self.assertEqual(args.count(name), 1)
        self.assertIn(b"My YouTube", args)
        self.assertFalse(any(b"*" in argument for argument in args))

    def test_missing_account_patch_is_always_rejected(self):
        (self.root / "ytplus.deb").touch()
        result = subprocess.run([str(ROOT / "scripts/inject-tweaks.sh"), "in.ipa", "out.ipa", "YouTube", "test"],
                                cwd=self.root, env=dict(os.environ, REQUIRE_BACKGROUND_FIX="false"), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"mandatory YTLAccountless", result.stderr)

    def test_duplicate_system_libraries_from_the_crashing_ipa_are_removed(self):
        libraries = ("/usr/lib/libz.1.dylib", "/usr/lib/libSystem.B.dylib", "@rpath/YTLite.dylib",
                     "/usr/lib/libz.1.dylib", "/usr/lib/libSystem.B.dylib", "@rpath/" + PATCH_NAME)
        original = binary(libraries)
        with self.assertRaisesRegex(ValueError, "duplicate linked dylib"):
            verify.macho(original)
        cleaned = prepare.remove_patch_loads(original, prepare.REPLACED)
        self.assertEqual(verify.macho(cleaned)[0], list(libraries[:2]))
        self.assertEqual(len(cleaned), len(original))

    def test_removal_cannot_renumber_a_live_chained_import(self):
        for referenced in (1, 2):
            original = bytearray(binary(("@rpath/" + PATCH_NAME, "/usr/lib/libz.1.dylib")))
            offset = len(original) + 16
            fixups = struct.pack("<7I", 0, 0, 28, 32, 1, 1, 0) + struct.pack("<I", referenced)
            command = struct.pack("<4I", 0x80000034, 16, offset, len(fixups))
            count, size = struct.unpack_from("<II", original, 16)
            struct.pack_into("<II", original, 16, count + 1, size + 16)
            original += command + fixups
            with self.assertRaisesRegex(ValueError, "live symbol bindings"):
                prepare.remove_patch_loads(bytes(original))

    def test_enabled_but_missing_patch_fails_before_cyan(self):
        (self.root / "ytplus.deb").touch()
        self.patch_file.unlink()
        result = subprocess.run([str(ROOT / "scripts/inject-tweaks.sh"), "input.ipa", "output.ipa", "YouTube", "test.app"],
                                cwd=self.root, env=dict(os.environ, REQUIRE_BACKGROUND_FIX="true"), capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b"compiled dylib is missing", result.stderr)

    def response(self, data, filename=None):
        response = io.BytesIO(data)
        response.headers = Message()
        if filename:
            response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    def test_downloads_binary_from_extensionless_url(self):
        with patch.object(download, "urlopen", return_value=self.response(self.expected, "New fix.dylib")):
            files = download.download_files("\n https://example.test/download?id=1 \n", self.root)
        self.assertEqual(files[0].name, "New fix.dylib")
        self.assertEqual(files[0].read_bytes(), self.expected)

    def test_downloads_deb(self):
        data = b"!<arch>\ndebian-binary   " + bytes(80)
        with patch.object(download, "urlopen", return_value=self.response(data)):
            files = download.download_files("https://example.test/tweak.deb", self.root)
        self.assertEqual(files[0].read_bytes(), data)

    def test_multiple_urls_accept_spaces_and_newlines(self):
        data = b"!<arch>\ndebian-binary   " + bytes(80)
        with patch.object(download, "urlopen", side_effect=[self.response(data), self.response(self.expected)]):
            files = download.download_files("https://example.test/a.deb \n https://example.test/b.dylib", self.root)
        self.assertEqual([p.name for p in files], ["a.deb", "b.dylib"])

    def test_invalid_download_and_existing_file_are_rejected(self):
        for data, name, message in ((b"<html>error</html>", "bad.dylib", "expected a Debian"),
                                    (self.expected, PATCH_NAME, "already exists")):
            with self.subTest(name=name), patch.object(download, "urlopen", return_value=self.response(data, name)):
                with self.assertRaisesRegex(ValueError, message):
                    download.download_files("https://example.test/file", self.root)

    def test_empty_optional_downloads_do_nothing(self):
        with patch.object(download, "urlopen") as request:
            self.assertEqual(download.download_files(" \n\n", self.root), [])
            request.assert_not_called()


if __name__ == "__main__":
    unittest.main()
