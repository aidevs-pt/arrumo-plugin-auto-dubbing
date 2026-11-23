<p align="center">
  <img src="icon.svg" width="88" height="88" alt="">
</p>

<h1 align="center">Auto-Dubbing for Arrumo AI Video Editor</h1>

<p align="center">Dub finished videos into other languages and translate their subtitles, keeping every cue on time.</p>

<p align="center">
  <a href="LICENSE"><img alt="License: AGPL-3.0" src="https://img.shields.io/badge/license-AGPL--3.0-2337B4"></a>
  <img alt="Bundled with Arrumo" src="https://img.shields.io/badge/bundled%20with-Arrumo-2337B4">
  <a href="https://www.aidevs.pt/tools/arrumo/docs/plugins/auto-dubbing/dub-a-video"><img alt="Docs in English, Spanish and Portuguese" src="https://img.shields.io/badge/docs-EN%20%C2%B7%20ES%20%C2%B7%20PT-111"></a>
</p>

This plugin ships with [Arrumo AI Video Editor](https://github.com/aidevs-pt/arrumo-video-editor), the free, open-source desktop app where an AI agent writes, designs, voices and cuts your videos and you approve every step. It comes installed with Arrumo; turn it on or off in **Settings › Plugins**.

## Guides

- **Dub a video**: [English](https://www.aidevs.pt/tools/arrumo/docs/plugins/auto-dubbing/dub-a-video) · [Español](https://www.aidevs.pt/es/tools/arrumo/docs/plugins/auto-dubbing/dub-a-video) · [Português](https://www.aidevs.pt/pt/tools/arrumo/docs/plugins/auto-dubbing/dub-a-video)

## How it works

The isolated backend currently prepares text for translation and reassembles translated subtitles. Its workspace actions accept the same SRT source for both calls.

| Action | Input | Result |
| --- | --- | --- |
| `read-subtitle-cues` | `{"subtitles":"<source SRT>"}` | `{"cues":[{"cue":1,"text":"<source text>"}]}` |
| `assemble-translated-subtitles` | `{"subtitles":"<source SRT>","translations":[{"cue":1,"text":"<translated text>"}]}` | `{"subtitles":"<translated SRT>"}` |

The `plan-speech` workspace action accepts `{"subtitles":"<translated SRT>"}` and returns `{"segments":[{"cue":1,"startMillis":125,"endMillis":1900,"text":"<translated text>"}]}` in source cue order. Each segment gives the speech provider its text and the caller the cue's placement window. Overlapping cues retain their individual windows.

Cue numbers are one-based positions. Send one translated text per source cue. Translations may arrive in any order, and the assembled file retains the original cue timestamps. Success is wrapped as `{"ok":true,"result":{...}}`. Invalid input returns `{"ok":false,"error":"<code>"}`.

Callers can save the assembled SRT as a language track on the selected verified output. Each action is subject to the SDK's 64 KiB request and response limits. Automatic translation and speech synthesis are pending.

## Render supplied speech clips locally

Place the synthesized PCM WAV for each cue at `<cue>.wav` in a local directory. Save the `segments` from `plan-speech` and the target duration in milliseconds as a JSON object with `segments` and `durationMillis`. Run:

```sh
python3 tools/render-voiceover.py plan.json /path/to/clips /path/to/new-voiceover.wav
```

The renderer places each clip at its cue start, trims clips that extend beyond their cue window, mixes overlapping cues, and pads the result to the requested duration. It requires FFmpeg on the path and produces 48 kHz mono PCM. To produce a dubbed MP4, pass the source video. The renderer requires the plan duration to match the video stream. It copies the picture and existing audio streams and adds the voiceover as the default audio track.

```sh
python3 tools/render-voiceover.py plan.json /path/to/clips /path/to/dubbed.mp4 --video /path/to/source.mp4
```

These commands run locally outside the isolated component. Editor integration remains pending.

## Translate a completed subtitle track

Use a local translator executable that accepts `{"targetLanguage":"de","cues":[{"cue":1,"text":"Hello"}]}` on stdin and returns `{"translations":[{"cue":1,"text":"Hallo"}]}` on stdout. Auto-Dubbing preserves source timestamps and validates cue coverage before saving the translation.

```sh
python3 tools/translate-completed-subtitles.py /path/to/arrumo-workspaces /path/to/workspaces.sqlite \
  1 42 3 de /path/to/translator
```

The command reads the latest primary subtitles and creates the language track. Pass `--expected-revision` to update an existing track. The saved revision can be used immediately by the dubbing command below. Select a bundled provider by passing `--translator-plugin codex` or `--translator-plugin claude-code` in place of the executable path. This uses the sibling plugin source checkouts or the directory supplied by `ARRUMO_PLUGIN_SOURCE_ROOT`. When using tools from a release ZIP, set `ARRUMO_PLUGIN_SOURCE_ROOT` if selecting a translator by plugin ID. Translator credentials belong to the adapter executable. The editor does not launch this command automatically.

## Dub completed outputs

The checkout tool can use a translated SRT already saved on a verified output. It reads each selected video and subtitle revision through the editor CLI, invokes the bundled Auto-Dubbing action, requests speech for each cue, and imports and attaches the resulting MP4.

```sh
python3 tools/dub-completed-output.py /path/to/arrumo-workspaces /path/to/workspaces.sqlite \
  1 42 3 es elevenlabs YOUR_VOICE_ID --audio-format mp3
```

The numeric arguments select workspace, run, and format. Pass `--revision` to pin a particular subtitle revision. The tool reads the response format, credential presence and cue length limit from the editor before requesting any speech. Pass `--audio-format` only to require a specific format. Use `all` in place of the format ID for every verified output or repeat `--additional-format <id>` to add specific formats. Add `--translator /path/to/translator` or `--translator-plugin <id>` to create missing language tracks before synthesis. Existing tracks are reused, and newly translated tracks remain available if dubbing fails. Choose one of `--translator`, `--translator-plugin`, or `--revision`. The command checks every selected video and subtitle track before requesting speech. Repeated cue text shares one synthesis result within the invocation.

Add `--dry-run` to inspect each selected format, its subtitle status, and the deduplicated request and character counts for existing tracks. When a track is missing, the speech estimate is incomplete. The preview makes no translation or speech requests and writes no files to the workspace.

Pass `--speech-cache /path/to/private-cache` to reuse successful cue audio across attempts. The cache key includes workspace, provider adapter digest, voice, and exact cue text. The files contain the generated audio. Dry runs report known cache hits without creating the cache directory. Use the same cache path when retrying a failed batch. Concurrent runs using that path wait for in-progress synthesis for a matching cue and reuse the published audio. Keep the cache on a local filesystem that supports process locks.

Use `python3 tools/prune-speech-cache.py /path/to/private-cache --max-age-days 30 --max-bytes 1073741824` to remove expired clips and bring the cache under a size limit. Add `--dry-run` to preview the removals. Retention uses the last reuse time and skips clips held by another run. Small coordination lock files remain available for future cache users.

A batch reports its completed formats and stops at the first processing failure. Its JSON includes the failed format and any skipped format IDs. The editor verifies and attaches each rendered variant in one operation. Rejected variants leave no managed asset. Published translator package dispatch and desktop invocation remain pending.

For the isolated Linux render path, append `--media-runner /path/to/sdk/tools/run_media_package.py --package-sha256 <reviewed-digest>`. The editor exports the exact Auto-Dubbing package selected in its catalog. The worker receives a copy of the selected source video, cue WAVs and timing windows. The local command verifies the returned media path. The editor verifies dimensions, duration, and audio before attaching it. Use a package that includes the media worker entrypoint.

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

Run the following from the intended release revision. The command pins the SDK checkout, Rust toolchain and WebAssembly tooling and prints the ZIP's SHA-256 for the registry. Release ZIPs include the isolated backend, license, documentation and local workflow tools. Run the tools with Python after verifying the release digest and extracting the ZIP to a local directory. The editor executes the Wasm actions in its plugin runtime. The Python commands use the local editor CLI and FFmpeg.

```sh
rustup target add --toolchain 1.100.0 wasm32-unknown-unknown
tools/package-release.sh /path/to/pinned/plugin-sdk /tmp/arrumo-auto-dubbing.zip
```

Install Python `jsonschema` and place `wasm-tools` 1.262.0 on the path before running the command.

## Render supplied clips with the isolated worker

The release includes `tools/render-media-worker.py`. Use the SDK media
package runner with that entrypoint and `--include tools/voiceover.py`.
Supply a dedicated input directory containing `source.mp4`, `plan.json`
and the numbered cue WAV files. The worker writes `dubbed.mp4` and
`result.json` to the output directory. Translation and speech synthesis
happen before this isolated media step.

## Contributing

Contributions are welcome: read [CONTRIBUTING.md](CONTRIBUTING.md) and our [Code of Conduct](CODE_OF_CONDUCT.md). Report security problems privately as described in [SECURITY.md](SECURITY.md).

## License

Copyright © 2026 DEVS AI Unipessoal LDA. Licensed under the [GNU Affero General Public License v3.0](LICENSE). Built by [DEVS AI](https://aidevs.pt), who make custom AI solutions for companies.
