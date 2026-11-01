#!/bin/bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
logos="${LOGOS:-${THEOS:-}/bin/logos.pl}"
output="${1:-$repo_dir/packages/YTLBackgroundPlaybackFix.dylib}"
if [[ "$output" != /* ]]; then
    output="$PWD/$output"
fi
if [[ ! -f "$logos" ]]; then
    echo "Set LOGOS to logos.pl, or set THEOS to your Theos installation." >&2
    exit 1
fi

build_dir="$(mktemp -d "${TMPDIR:-/tmp}/ytlite-background-build.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT
cd "$repo_dir"
mkdir -p "$(dirname "$output")" "$build_dir/CydiaSubstrate.framework"

# Link only the APIs provided by the existing injected libraries. Do not bundle
# another YTLUserDefaults class or replace the user's installed YTLite binary.
cat > "$build_dir/libYTLite.tbd" <<'TBD'
--- !tapi-tbd
tbd-version: 4
targets: [ arm64-ios ]
install-name: '@rpath/YTLite.dylib'
current-version: 0.0.0
compatibility-version: 0.0.0
exports:
  - targets: [ arm64-ios ]
    objc-classes: [ YTLUserDefaults ]
...
TBD

cat > "$build_dir/CydiaSubstrate.framework/CydiaSubstrate.tbd" <<'TBD'
--- !tapi-tbd
tbd-version: 4
targets: [ arm64-ios ]
install-name: '@rpath/CydiaSubstrate.framework/CydiaSubstrate'
current-version: 0.0.0
compatibility-version: 0.0.0
exports:
  - targets: [ arm64-ios ]
    symbols: [ _MSHookMessageEx ]
...
TBD

perl "$logos" BackgroundPlayback.x > "$build_dir/BackgroundPlayback.m"
perl "$logos" BedtimeReminders.x > "$build_dir/BedtimeReminders.m"
sdk="$(xcrun --sdk iphoneos --show-sdk-path)"
xcrun --sdk iphoneos clang -target arm64-apple-ios13.0 -isysroot "$sdk" \
    -dynamiclib -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror \
    -I "$repo_dir" -I "$repo_dir/tests/include" \
    "$build_dir/BackgroundPlayback.m" "$build_dir/BedtimeReminders.m" \
    -L "$build_dir" -lYTLite -F "$build_dir" -framework CydiaSubstrate \
    -framework Foundation \
    -install_name '@rpath/YTLBackgroundPlaybackFix.dylib' \
    -Wl,-rpath,@loader_path -o "$output"
codesign --force --sign - "$output"
printf 'Built %s\n' "$output"
