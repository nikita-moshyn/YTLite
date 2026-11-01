#!/bin/bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
logos="${LOGOS:-${THEOS:-}/bin/logos.pl}"
output="${1:-$repo_dir/packages/YTLAccountless.dylib}"
[[ "$output" == /* ]] || output="$PWD/$output"
[[ -f "$logos" ]] || { echo "Set LOGOS to logos.pl" >&2; exit 1; }
build_dir="$(mktemp -d "${TMPDIR:-/tmp}/ytlite-accountless.XXXXXX")"
trap 'rm -rf "$build_dir"' EXIT
mkdir -p "$(dirname "$output")" "$build_dir/CydiaSubstrate.framework"
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
perl "$logos" "$repo_dir/Accountless.x" > "$build_dir/Accountless.m"
sdk="$(xcrun --sdk iphoneos --show-sdk-path)"
xcrun --sdk iphoneos clang -target arm64-apple-ios13.0 -isysroot "$sdk" \
    -dynamiclib -fobjc-arc -fblocks -O2 -Wall -Wextra -Werror \
    -I "$repo_dir/tests/include" "$build_dir/Accountless.m" \
    -F "$build_dir" -framework CydiaSubstrate -framework Foundation \
    -install_name '@rpath/YTLAccountless.dylib' -Wl,-rpath,@loader_path -o "$output"
codesign --force --sign - "$output"
printf 'Built %s\n' "$output"
