#!/usr/bin/env python3
"""Render and attach a dub for one completed Arrumo output and existing translated track."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

from voiceover import render_voiceover, validate_windows, video_duration_ms


def dub_output(args):
    def editor(operation, *arguments, data=None):
        result = subprocess.run(
            [args.editor, args.database, operation, *map(str, arguments)],
            input=data, stdout=subprocess.PIPE, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout) if result.stdout else None

    language = args.language.lower()
    if not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", language) or len(language) > 63:
        raise ValueError("Invalid subtitle language tag")
    scope = (args.workspace, args.run, args.format)
    source = Path(editor("verified-video-source", *scope))
    duration = round(video_duration_ms(source))
    track = editor("completed-subtitle-track", *scope, language, *args.revision)
    request = json.dumps({"subtitles": track["subtitles"]}, ensure_ascii=False)
    if len(request.encode("utf-8")) > 60 * 1024:
        raise ValueError("Translated track exceeds the plugin action input budget")
    result = editor("invoke-plugin-action", "auto-dubbing", "plan-speech", args.workspace, data=request)
    if not result.get("ok"):
        raise ValueError("Auto-Dubbing could not plan speech for the translated track")
    segments = result["result"]["segments"]
    validate_windows(duration, segments)
    if any(not isinstance(segment["text"], str) or not segment["text"].strip() for segment in segments):
        raise ValueError("Speech plan contains invalid cue text")

    with tempfile.TemporaryDirectory(prefix="arrumo-dub-") as temporary:
        scratch = Path(temporary)
        for segment in segments:
            cue = segment["cue"]
            clip = scratch / f"{cue}.wav"
            raw = clip if args.audio_format == "wav" else scratch / f"{cue}.mp3"
            editor("synthesize-speech", args.workspace, args.provider, args.voice, raw, data=segment["text"])
            if args.audio_format == "mp3":
                subprocess.run([
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-f", "mp3", "-i", str(raw), "-map", "0:a:0", "-c:a", "pcm_s16le", str(clip),
                ], check=True)
                raw.unlink()
        dubbed = scratch / f"dubbed-{language}.mp4"
        render_voiceover({"durationMillis": duration, "segments": segments}, scratch, dubbed, source)
        asset = editor("import-asset", args.workspace, dubbed)
        try:
            editor("attach-completed-media", *scope, asset["id"])
        except subprocess.CalledProcessError as error:
            raise ValueError(f"Dub imported as workspace asset {asset['id']}. Attachment failed.") from error
        return {"assetId": asset["id"], "formatId": args.format, "subtitleRevision": track["revision"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editor", type=Path, help="path to arrumo-workspaces")
    parser.add_argument("database", type=Path)
    parser.add_argument("workspace", type=int)
    parser.add_argument("run", type=int)
    parser.add_argument("format", type=int)
    parser.add_argument("language")
    parser.add_argument("provider")
    parser.add_argument("voice")
    parser.add_argument("--audio-format", choices=["mp3", "wav"], required=True)
    parser.add_argument("--revision", type=int)
    args = parser.parse_args()
    args.revision = [] if args.revision is None else [args.revision]
    try:
        print(json.dumps(dub_output(args)))
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
