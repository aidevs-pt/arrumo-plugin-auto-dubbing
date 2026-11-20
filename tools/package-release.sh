#!/bin/sh
set -eu

if [ "$#" -ne 2 ]; then
  printf '%s\n' 'Usage: tools/package-release.sh <sdk-checkout> <new-output.zip>' >&2
  exit 2
fi

sdk=$1
output=$2
source=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
sdk_commit=9ba73a07d60f5da04e4715ce9ed6fbe6d5ae2ac3
toolchain=1.100.0

if [ "$(git -C "$sdk" rev-parse HEAD)" != "$sdk_commit" ] ||
  ! git -C "$sdk" diff --quiet HEAD -- tools/package_plugin.py manifest.schema.json wit/plugin.wit; then
  printf 'Use an unmodified SDK checkout at %s.\n' "$sdk_commit" >&2
  exit 1
fi

case "$(wasm-tools --version)" in
  'wasm-tools 1.262.0'|'wasm-tools 1.262.0 ('*) ;;
  *) printf '%s\n' 'Use wasm-tools 1.262.0.' >&2; exit 1 ;;
esac

cmp "$source/wit/plugin.wit" "$sdk/wit/plugin.wit"

pending=$(mktemp -d)
trap 'rm -r -- "$pending"' EXIT
cargo "+$toolchain" build --manifest-path "$source/Cargo.toml" --locked --release \
  --target wasm32-unknown-unknown --target-dir "$pending/target"
wasm-tools component new \
  "$pending/target/wasm32-unknown-unknown/release/arrumo_auto_dubbing.wasm" \
  -o "$pending/backend.wasm"
wasm-tools validate "$pending/backend.wasm"
cp "$source/manifest.json" "$source/LICENSE" "$source/README.md" "$pending/"
mkdir "$pending/tools"
set -- --include backend.wasm --include LICENSE --include README.md
for tool in dub-completed-output.py render-voiceover.py translate-completed-subtitles.py subtitle_translation.py voiceover.py; do
  cp "$source/tools/$tool" "$pending/tools/$tool"
  set -- "$@" --include "tools/$tool"
done
python3 "$sdk/tools/package_plugin.py" "$pending" "$output" "$@"
