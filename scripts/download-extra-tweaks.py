#!/usr/bin/env python3
"""Download optional workflow inputs as files consumed by inject-tweaks.sh."""
import os
from pathlib import Path
import shutil
import struct
import tempfile
from urllib.parse import unquote, urlparse
from urllib.request import urlopen


def is_arm64_dylib(path):
    with path.open("rb") as stream:
        header = stream.read(32)
        if header[:4] == b"\xca\xfe\xba\xbe":
            for index in range(struct.unpack_from(">I", header, 4)[0]):
                # Read fat records independently of the selected slice header.
                position = 8 + index * 20
                stream.seek(position)
                cpu, _, offset, _, _ = struct.unpack(">5I", stream.read(20))
                if cpu == 0x100000C:
                    stream.seek(offset)
                    header = stream.read(32)
                    break
        return (len(header) >= 16 and header[:4] == b"\xcf\xfa\xed\xfe"
                and struct.unpack_from("<I", header, 4)[0] == 0x100000C
                and struct.unpack_from("<I", header, 12)[0] == 6)


def download_files(urls, destination):
    destination = Path(destination)
    downloaded = []
    for index, url in enumerate(urls.split(), 1):
        url = url.strip()
        if not url:
            continue
        parsed = urlparse(url)
        if parsed.scheme not in ("https", "http") or not parsed.netloc:
            raise ValueError(f"Entry {index}: expected an HTTP(S) download URL")
        with tempfile.TemporaryDirectory(dir=destination) as temporary:
            pending = Path(temporary) / "download"
            with urlopen(url, timeout=45) as response, pending.open("wb") as stream:
                name = response.headers.get_filename() or Path(unquote(parsed.path)).name
                shutil.copyfileobj(response, stream)
            with pending.open("rb") as stream:
                header = stream.read(128)
            if header.startswith(b"!<arch>\n") and b"debian-binary" in header:
                suffix = ".deb"
            elif is_arm64_dylib(pending):
                suffix = ".dylib"
            else:
                raise ValueError(f"Entry {index}: expected a Debian package or arm64 dylib")
            name = Path(name).name
            if name in ("", ".", "..") or name.startswith("-") or not name.endswith(suffix):
                name = f"extra-tweak-{index}{suffix}"
            target = destination / name
            if target.exists():
                raise ValueError(f"Entry {index}: {name} already exists; refusing to replace it")
            shutil.move(pending, target)
            downloaded.append(target)
    return downloaded


if __name__ == "__main__":
    for path in download_files(os.environ.get("EXTRA_TWEAKS_URLS", ""), Path.cwd()):
        print(f"Downloaded additional tweak: {path.name}")
