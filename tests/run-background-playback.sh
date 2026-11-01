#!/bin/bash
set -euo pipefail

repo_dir="$(cd "$(dirname "$0")/.." && pwd)"
logos="${LOGOS:-${THEOS:-}/bin/logos.pl}"
if [[ ! -f "$logos" ]]; then
    echo "Set LOGOS to logos.pl, or set THEOS to your Theos installation." >&2
    exit 1
fi

test_dir="$(mktemp -d "${TMPDIR:-/tmp}/ytlite-background-tests.XXXXXX")"
trap 'rm -rf "$test_dir"' EXIT
cd "$repo_dir"
perl "$logos" BackgroundPlayback.x > "$test_dir/BackgroundPlayback.m"

for variant in 0 1 2 3 4; do
    xcrun --sdk macosx clang -fobjc-arc -fblocks -Wall -Wextra -Werror \
        -I "$repo_dir" -I "$repo_dir/tests/include" \
        -DPOLICY_VARIANT="$variant" \
        "$test_dir/BackgroundPlayback.m" "$repo_dir/tests/background_playback.m" \
        -framework Foundation -Wl,-ignore_auto_link \
        -o "$test_dir/test-$variant"
    "$test_dir/test-$variant"
done

perl "$logos" BedtimeReminders.x > "$test_dir/BedtimeReminders.m"
for variant in 0 1 2; do
    xcrun --sdk macosx clang -fobjc-arc -fblocks -Wall -Wextra -Werror \
        -I "$repo_dir/tests/include" -DREMINDER_VARIANT="$variant" \
        "$test_dir/BedtimeReminders.m" "$repo_dir/tests/bedtime_reminders.m" \
        -framework Foundation -Wl,-ignore_auto_link \
        -o "$test_dir/bedtime-$variant"
    "$test_dir/bedtime-$variant"
done
