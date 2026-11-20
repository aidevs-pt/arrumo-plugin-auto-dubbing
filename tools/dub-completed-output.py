#!/usr/bin/env python3
"""Render and attach a dub for selected completed Arrumo output formats."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

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
    credential_configured = provider["credentialSource"] in ("workspace", "app")
    if not args.dry_run and not credential_configured:
        raise ValueError("Speech provider credential is not configured")
    text_limit = provider["maxTextCharacters"]

    cache = args.speech_cache
    if cache and (cache.is_symlink() or (cache.exists() and not cache.is_dir())):
        raise ValueError("Speech cache must be a local directory")
    if cache:
        adapter_digest = provider["adapterSha256"]
        if not re.fullmatch(r"[0-9a-f]{64}", adapter_digest):
            raise ValueError("Speech adapter identity is unavailable")

    def cached_clip(text):
        if not cache:
            return None
        key = json.dumps([
            1, str(args.database.resolve()), args.workspace, args.provider, args.voice,
            provider["credentialSource"], adapter_digest, audio_format, text,
        ], ensure_ascii=False)
        name = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return cache / f"{name}.wav"

    translator = None
    if args.translator_plugin:
        translator = bundled_translator(editor, args.translator_plugin)
    elif args.translator:
        translator = [args.translator.resolve(strict=True)]
    plans = []
    missing = {}
    for format_id in formats:
        scope = (args.workspace, args.run, format_id)
        try:
            source = Path(editor("verified-video-source", *scope))
            duration = round(video_duration_ms(source))
            revision = [] if args.revision is None else [args.revision]
            if (translator or args.dry_run) and language not in editor("completed-subtitle-languages", *scope):
                if args.dry_run:
                    missing[format_id] = {
                        "formatId": format_id, "durationMillis": duration,
                        "status": "translation_pending" if translator else "subtitle_track_missing",
                    }
                    continue
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

    if args.dry_run:
        output_plans = {
            scope[2]: {
                "formatId": scope[2], "durationMillis": duration,
                "status": "ready", "subtitleRevision": revision, "cueCount": len(segments),
            }
            for scope, _, duration, revision, segments in plans
        }
        output_plans.update(missing)
        texts = {segment["text"] for *_, segments in plans for segment in segments}
        hits = {text for text in texts if cache and is_cached_clip(cached_clip(text))}
        return {
            "language": language,
            "provider": args.provider,
            "responseFormat": audio_format,
            "credentialConfigured": credential_configured,
            "outputs": [output_plans[format_id] for format_id in formats],
            "knownSpeechRequests": len(texts),
            "knownSpeechCharacters": sum(map(len, texts)),
            "cachedSpeechRequests": len(hits),
            "uncachedSpeechRequests": len(texts - hits),
            "speechEstimateComplete": not missing,
        }

    completed = []
    with tempfile.TemporaryDirectory(prefix="arrumo-dub-") as temporary:
        scratch = Path(temporary)
        clips = {}
        package = None
        if args.media_runner:
            runner = args.media_runner.resolve(strict=True)
            package = scratch / "reviewed.zip"
            editor("export-plugin-package", "auto-dubbing", args.package_sha256, package)
            with zipfile.ZipFile(package) as archive:
                for name in ("tools/render-media-worker.py", "tools/voiceover.py"):
                    if name not in archive.NameToInfo or archive.getinfo(name).file_size == 0:
                        raise ValueError("Reviewed package does not contain the dubbing media worker")
        for index, (scope, source, duration, revision, segments) in enumerate(plans):
            format_id = scope[2]
            try:
                target = scratch / str(format_id)
                target.mkdir()
                for segment in segments:
                    text = segment["text"]
                    if text not in clips:
                        stem = scratch / f"speech-{len(clips)}"
                        cached = stem.with_suffix(".wav")
                        cache_file = cached_clip(text)
                        if cache_file and is_cached_clip(cache_file):
                            shutil.copyfile(cache_file, cached)
                        else:
                            raw = stem.with_suffix(f".{audio_format}")
                            editor("synthesize-speech", args.workspace, args.provider, args.voice, raw, data=text)
                            if audio_format == "mp3":
                                subprocess.run([
                                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                                    "-f", "mp3", "-i", str(raw), "-map", "0:a:0", "-c:a", "pcm_s16le", str(cached),
                                ], check=True)
                                raw.unlink()
                            if cache_file:
                                publish_cached_clip(cached, cache_file)
                        clips[text] = cached
                    (target / f"{segment['cue']}.wav").hardlink_to(clips[text])
                dubbed = target / f"dubbed-{language}-{format_id}.mp4"
                plan = {
                    "durationMillis": duration,
                    "segments": [{key: segment[key] for key in ("cue", "startMillis", "endMillis")}
                                 for segment in segments],
                }
                if package is None:
                    render_voiceover(plan, target, dubbed, source)
                else:
                    shutil.copyfile(source, target / "source.mp4")
                    (target / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
                    worker_output = scratch / f"rendered-{format_id}"
                    result = subprocess.run([
                        sys.executable, runner, package,
                        "--sha256", args.package_sha256,
                        "--inputs", target, "--output", worker_output,
                        "--entrypoint", "tools/render-media-worker.py",
                        "--include", "tools/voiceover.py",
                    ], capture_output=True, encoding="utf-8", check=True, timeout=130)
                    artifact = Path(json.loads(result.stdout)["file"])
                    if artifact.resolve(strict=True) != worker_output / "dubbed.mp4" or artifact.is_symlink():
                        raise ValueError("Media worker output path differs from the requested artifact")
                    if abs(video_duration_ms(artifact) - duration) > 1:
                        raise ValueError("Media worker output duration differs from the source")
                    artifact.rename(dubbed)
                asset_id = editor("import-completed-video-variant", *scope, dubbed)["id"]
            except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
                failure = {"formatId": format_id, "error": str(error)}
                return {"completed": completed, "failed": failure, "skipped": formats[index + 1:]}
            completed.append({"assetId": asset_id, "formatId": format_id, "subtitleRevision": revision})
    return {"completed": completed} if args.format == "all" or args.additional_format else completed[0]


def is_cached_clip(path):
    if path.is_symlink() or (path.exists() and (not path.is_file() or path.stat().st_size == 0)):
        raise ValueError("Invalid cached speech clip")
    return path.is_file()


def publish_cached_clip(source, destination):
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".arrumo-speech-") as directory:
        pending = Path(directory) / "clip.wav"
        shutil.copyfile(source, pending)
        with pending.open("r+b") as stream:
            os.fsync(stream.fileno())
        try:
            destination.hardlink_to(pending)
        except FileExistsError:
            if not is_cached_clip(destination):
                raise


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
    parser.add_argument("--speech-cache", type=Path, help="reuse successful speech clips from a private local directory")
    parser.add_argument("--dry-run", action="store_true", help="report output plans without dispatching translation or speech")
    parser.add_argument("--media-runner", type=Path, help="SDK Linux run_media_package.py path")
    parser.add_argument("--package-sha256", help="reviewed Auto-Dubbing package digest for the media runner")
    args = parser.parse_args()
    if bool(args.media_runner) != bool(args.package_sha256):
        parser.error("--media-runner and --package-sha256 must be provided together")
    try:
        result = dub_output(args)
        print(json.dumps(result))
        if "failed" in result:
            parser.exit(1)
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, zipfile.BadZipFile) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
