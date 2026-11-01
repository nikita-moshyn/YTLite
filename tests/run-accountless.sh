#!/bin/bash
set -euo pipefail
repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
logos="${LOGOS:-${THEOS:-}/bin/logos.pl}"
test_dir="$(mktemp -d "${TMPDIR:-/tmp}/ytlite-accountless-tests.XXXXXX")"
trap 'rm -rf "$test_dir"' EXIT
perl "$logos" "$repo_dir/Accountless.x" > "$test_dir/Accountless.m"
xcrun --sdk macosx clang -fobjc-arc -fblocks -Wall -Wextra -Werror \
    -I "$repo_dir/tests/include" "$test_dir/Accountless.m" "$repo_dir/tests/accountless.m" \
    -framework Foundation -Wl,-ignore_auto_link -o "$test_dir/accountless"
"$test_dir/accountless"
