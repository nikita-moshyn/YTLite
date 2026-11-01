import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("account_verifier", ROOT / "scripts/verify-accountless.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
native = verifier.native


class AccountRemovalTests(unittest.TestCase):
    def test_invalid_and_unreviewed_binaries_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "reviewed arm64"):
            native.transform(b"not a Mach-O")
        # A version label or matching class names cannot substitute for a
        # reviewed executable and its obfuscated branch/string data.
        with patch.object(native, "sections", return_value={key: (0, 0, len(b"unknown")) for key in native.PROFILE["sections"]}):
            with self.assertRaisesRegex(ValueError, "no version fallback"):
                native.transform(b"unknown")

    def test_unsanitized_deb_cannot_be_injected(self):
        with self.assertRaisesRegex(ValueError, "sanitized YTLite"):
            verifier.verify_native({"Library/YTLite.dylib": b"closed client"})

    def test_malformed_debian_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.deb"
            for data in (b"not a deb", b"!<arch>\nshort", b"!<arch>\n"):
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    verifier.deb_files(path)


@unittest.skipUnless(os.environ.get("YTPLUS_TEST_DEB"), "Set YTPLUS_TEST_DEB to the current original release DEB")
class CurrentBinaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = next(data for name, data in verifier.deb_files(os.environ["YTPLUS_TEST_DEB"]).items()
                            if name.endswith("/YTLite.dylib"))
        cls.patched = native.transform(cls.original)

    def test_current_release_is_removed_without_replacing_unrelated_code(self):
        native.verify(self.patched)
        self.assertEqual(len(self.original), len(self.patched))
        expected = bytearray(self.patched)
        for entry in native.PROFILE["patches"]:
            a = entry["offset"]
            expected[a:a + entry["size"]] = self.original[a:a + entry["size"]]
        self.assertEqual(bytes(expected), self.original)
        # Latest SponsorBlock fetch/playback routines and preference getters
        # retain their current implementation, including false local values.
        for a, b in ((0x194914, 0x19B208), (0x238C0, 0x239C8), (0x23A5C, 0x23B64)):
            self.assertEqual(self.patched[a:b], self.original[a:b])

    def test_an_unremoved_or_reintroduced_account_callback_is_rejected(self):
        restored = bytearray(self.patched)
        callback = next(p for p in native.PROFILE["patches"] if p["offset"] == 0x26EB0)
        a = callback["offset"]
        restored[a:a + callback["size"]] = self.original[a:a + callback["size"]]
        with self.assertRaisesRegex(ValueError, "partially removed"):
            native.verify(bytes(restored))

    def test_changes_elsewhere_cannot_bypass_the_code_hash(self):
        changed = bytearray(self.patched)
        changed[0x194A04] ^= 1
        with self.assertRaisesRegex(ValueError, "differs from the reviewed"):
            native.verify(bytes(changed))

    def test_fake_accountless_receipt_cannot_hide_the_original_client(self):
        files = {"Library/YTLite.dylib": self.original,
                 "Library/YTLite.bundle/YTLOffline.json": json.dumps({"account_code_removed": True}).encode()}
        with self.assertRaisesRegex(ValueError, "partially removed"):
            verifier.verify_native(files)


if __name__ == "__main__":
    unittest.main()
