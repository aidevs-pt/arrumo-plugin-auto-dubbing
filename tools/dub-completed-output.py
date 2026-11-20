#!/usr/bin/env python3
"""Render and attach a dub for selected completed Arrumo output formats."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

from subtitle_translation import bundled_translator, translate_track
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
    if args.format == "all":
        if args.additional_format:
            raise ValueError("Use either all formats or explicit format IDs")
        completed = editor("completed-video", args.workspace, args.run)
        formats = [output["format_id"] for output in completed["delivery"]["verified_outputs"]]
    else:
        formats = [int(args.format), *args.additional_format]
    if not formats or any(format_id <= 0 for format_id in formats) or len(set(formats)) != len(formats):
        raise ValueError("Select one or more distinct verified format IDs")

    provider = editor("speech-provider-status", args.workspace, args.provider)
    audio_format = provider["responseFormat"]
    if audio_format not in ("mp3", "wav") or (args.audio_format and args.audio_format != audio_format):
        raise ValueError("Requested audio format differs from the speech provider response format")
    if provider["credentialSource"] not in ("workspace", "app"):
        raise ValueError("Speech provider credential is not configured")
    text_limit = provider["maxTextCharacters"]

    translator = None
    if args.translator_plugin:
        translator = bundled_translator(editor, args.translator_plugin)
    elif args.translator:
        translator = [args.translator.resolve(strict=True)]
    plans = []
    for format_id in formats:
        scope = (args.workspace, args.run, format_id)
        try:
            source = Path(editor("verified-video-source", *scope))
            duration = round(video_duration_ms(source))
            revision = [] if args.revision is None else [args.revision]
            if translator and language not in editor("completed-subtitle-languages", *scope):
                translated = translate_track(editor, scope, language, translator)
                revision = [translated["revision"]]
            track = editor("completed-subtitle-track", *scope, language, *revision)
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
            if any(len(segment["text"]) > text_limit for segment in segments):
                raise ValueError(f"A cue exceeds the speech provider limit of {text_limit} characters")
        except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
            raise ValueError(f"Format {format_id} preflight failed: {error}") from error
        plans.append((scope, source, duration, track["revision"], segments))

    completed = []
    with tempfile.TemporaryDirectory(prefix="arrumo-dub-") as temporary:
        scratch = Path(temporary)
        clips = {}
        for index, (scope, source, duration, revision, segments) in enumerate(plans):
            format_id = scope[2]
            asset_id = None
            try:
                target = scratch / str(format_id)
                target.mkdir()
                for segment in segments:
                    text = segment["text"]
                    if text not in clips:
                        stem = scratch / f"speech-{len(clips)}"
                        cached = stem.with_suffix(".wav")
                        raw = stem.with_suffix(f".{audio_format}")
                        editor("synthesize-speech", args.workspace, args.provider, args.voice, raw, data=text)
                        if audio_format == "mp3":
                            subprocess.run([
                                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                                "-f", "mp3", "-i", str(raw), "-map", "0:a:0", "-c:a", "pcm_s16le", str(cached),
                            ], check=True)
                            raw.unlink()
                        clips[text] = cached
                    (target / f"{segment['cue']}.wav").hardlink_to(clips[text])
                dubbed = target / f"dubbed-{language}-{format_id}.mp4"
                render_voiceover({"durationMillis": duration, "segments": segments}, target, dubbed, source)
                asset_id = editor("import-asset", args.workspace, dubbed)["id"]
                editor("attach-completed-media", *scope, asset_id)
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                failure = {"formatId": format_id, "error": str(error)}
                if asset_id is not None:
                    failure["assetId"] = asset_id
                return {"completed": completed, "failed": failure, "skipped": formats[index + 1:]}
            completed.append({"assetId": asset_id, "formatId": format_id, "subtitleRevision": revision})
    return {"completed": completed} if args.format == "all" or args.additional_format else completed[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editor", type=Path, help="path to arrumo-workspaces")
    parser.add_argument("database", type=Path)
    parser.add_argument("workspace", type=int)
    parser.add_argument("run", type=int)
    parser.add_argument("format", help="verified format ID or all")
    parser.add_argument("--additional-format", type=int, action="append", default=[])
    parser.add_argument("language")
    parser.add_argument("provider")
    parser.add_argument("voice")
    parser.add_argument("--audio-format", choices=["mp3", "wav"], help="optionally require this provider response format")
    subtitle_source = parser.add_mutually_exclusive_group()
    subtitle_source.add_argument("--revision", type=int)
    subtitle_source.add_argument("--translator-plugin", help="create missing tracks with a bundled local translator")
    subtitle_source.add_argument("--translator", type=Path, help="create missing translated tracks with this local adapter")
    args = parser.parse_args()
    try:
        result = dub_output(args)
        print(json.dumps(result))
        if "failed" in result:
            parser.exit(1)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
