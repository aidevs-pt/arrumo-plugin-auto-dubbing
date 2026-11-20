# Arrumo Auto-Dubbing Plugin

Dubbing and subtitle translation for selected video outputs using configured providers.

The isolated backend currently prepares text for translation and reassembles translated subtitles. Its workspace actions accept the same SRT source for both calls.

| Action | Input | Result |
| --- | --- | --- |
| `read-subtitle-cues` | `{"subtitles":"<source SRT>"}` | `{"cues":[{"cue":1,"text":"<source text>"}]}` |
| `assemble-translated-subtitles` | `{"subtitles":"<source SRT>","translations":[{"cue":1,"text":"<translated text>"}]}` | `{"subtitles":"<translated SRT>"}` |

The `plan-speech` workspace action accepts `{"subtitles":"<translated SRT>"}` and returns `{"segments":[{"cue":1,"startMillis":125,"endMillis":1900,"text":"<translated text>"}]}` in source cue order. Each segment gives the speech provider its text and the caller the cue's placement window. Overlapping cues retain their individual windows.

Cue numbers are one-based positions. Send one translated text per source cue. Translations may arrive in any order, and the assembled file retains the original cue timestamps. Success is wrapped as `{"ok":true,"result":{...}}`. Invalid input returns `{"ok":false,"error":"<code>"}`.

Callers can save the assembled SRT as a language track on the selected verified output. Each action is subject to the SDK's 64 KiB request and response limits. Automatic translation, speech synthesis and dubbed video rendering are pending.

## Build and package

From a checkout with the Arrumo Plugin SDK available at `../../plugin-sdk` and `wasm-tools` on the path:

```sh
rustup target add wasm32-unknown-unknown
cargo test --locked
cargo build --locked --release --target wasm32-unknown-unknown
wasm-tools component new target/wasm32-unknown-unknown/release/arrumo_auto_dubbing.wasm -o backend.wasm
python3 ../../plugin-sdk/tools/package_plugin.py . plugin.zip --include backend.wasm
```

The editor’s default debug build picks up `plugin.zip` from this sibling checkout. The package can also be installed manually in a core-only build. Published editor builds require a staged package whose digest is pinned in the official registry.

## Prepare a release artifact

Run the following from the intended release revision. The command pins the SDK checkout, Rust toolchain and WebAssembly tooling and prints the ZIP's SHA-256 for the registry.

```sh
rustup target add --toolchain 1.100.0 wasm32-unknown-unknown
tools/package-release.sh /path/to/pinned/plugin-sdk /tmp/arrumo-auto-dubbing.zip
```

Install Python `jsonschema` and place `wasm-tools` 1.262.0 on the path before running the command.

Copyright © 2026 DEVS AI Unipessoal LDA. Licensed under the [GNU Affero General Public License v3.0](LICENSE).

For custom AI solutions for your company, visit [DEVS AI](https://aidevs.pt).
