# Arrumo Auto-Dubbing Plugin

Dubbing and subtitle translation for selected video outputs using configured providers.

The isolated backend currently prepares text for translation and reassembles translated subtitles. Its workspace actions accept the same SRT source for both calls.

| Action | Input | Result |
| --- | --- | --- |
| `read-subtitle-cues` | `{"subtitles":"<source SRT>"}` | `{"cues":[{"cue":1,"text":"<source text>"}]}` |
| `assemble-translated-subtitles` | `{"subtitles":"<source SRT>","translations":[{"cue":1,"text":"<translated text>"}]}` | `{"subtitles":"<translated SRT>"}` |

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

Copyright © 2026 DEVS AI Unipessoal LDA. Licensed under the [GNU Affero General Public License v3.0](LICENSE).

For custom AI solutions for your company, visit [DEVS AI](https://aidevs.pt).
