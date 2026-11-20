# Dub a finished video

[Español](../es/dub-a-video.md) · [Português](../pt/dub-a-video.md)

Start with a verified delivery, a subtitle track in the target language, and a configured speech provider and voice. Run the following from the Auto-Dubbing checkout or from the extracted plugin package.

## Preview the request

This example selects workspace 1, run 42 and format 3. Replace those IDs, the paths, the language and the voice ID with your own. The preview reports available tracks and expected requests for known cues. It makes no provider calls.

```sh
python3 tools/dub-completed-output.py /path/to/arrumo-workspaces /path/to/workspaces.sqlite 1 42 3 es elevenlabs YOUR_VOICE_ID --dry-run
```

## Render and export

When the plan is ready, run the command again without the preview flag. Use all in place of the format ID to dub every verified output, or add specific IDs with `--additional-format`. If a translated track is missing, you can import it in the completed video or use a supported translator.

The tool attaches each successful dub to its output as an alternate MP4. Open the completed video to find the alternate or export the delivery ZIP. When a batch stops on an error, its report identifies the completed, failed and skipped formats.

See [the command reference](../../README.md#dub-completed-outputs) for translator, revision, cache and isolated renderer options.
