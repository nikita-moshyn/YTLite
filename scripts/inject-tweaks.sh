#!/bin/bash
set -euo pipefail

if [[ $# != 4 ]]; then
    echo "Usage: $0 input.ipa output.ipa display-name bundle-id" >&2
    exit 1
fi
[[ -f ytplus.deb ]] || { echo "Missing ytplus.deb" >&2; exit 1; }
if [[ "${REQUIRE_BACKGROUND_FIX:-false}" == true && ! -f YTLBackgroundPlaybackFix.dylib ]]; then
    echo "Background playback fix was enabled but its compiled dylib is missing." >&2
    exit 1
fi
[[ -f YTLAccountless.dylib ]] || { echo "Missing mandatory YTLAccountless.dylib" >&2; exit 1; }
script_dir="$(cd "$(dirname "$0")" && pwd)"
python3 "$script_dir/verify-accountless.py" --deb ytplus.deb

input="$1"
staging="$(mktemp -d "${TMPDIR:-/tmp}/ytlite-injection.XXXXXX")"
trap 'rm -rf "$staging"' EXIT
python3 "$script_dir/prepare-background-playback.py" "$input" "$staging/input.ipa" --replace-ytlite
input="$staging/input.ipa"

# Arrays preserve spaces and keep the published tweak from being injected twice.
tweaks=(ytplus.deb)
shopt -s nullglob
for file in *.deb *.dylib *.appex; do
    if [[ "$file" != ytplus.deb ]]; then
        tweaks+=("$file")
    fi
done
cyan -i "$input" -o "$2" --overwrite -uwef "${tweaks[@]}" -n "$3" -b "$4"
python3 "$script_dir/verify-accountless.py" "$2" --patch YTLAccountless.dylib
