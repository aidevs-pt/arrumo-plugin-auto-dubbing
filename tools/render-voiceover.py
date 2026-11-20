#!/usr/bin/env python3
"""Render timed speech clips to WAV or add them to a new MP4."""
import argparse
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import subprocess
import tempfile

MAX_SEGMENTS = 256
MAX_DURATION_MS = 24 * 60 * 60 * 1000
SAMPLE_RATE = 48_000


def render_voiceover(plan, clips, output, video=None):
    duration = plan["durationMillis"]
    segments = plan["segments"]
    if type(duration) is not int or not 0 < duration <= MAX_DURATION_MS:
        raise ValueError("Invalid voiceover duration")
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        raise ValueError(f"Expected 1 to {MAX_SEGMENTS} speech segments")
    extension = ".mp4" if video else ".wav"
    if output.suffix.lower() != extension or output.exists() or output.is_symlink():
        raise ValueError(f"Expected a new {extension} output path")
    if video is not None:
        verify_video_duration(video, duration)

    inputs = []
    filters = []
    cues = set()
    for index, segment in enumerate(segments):
        cue, start, end = (segment[key] for key in ("cue", "startMillis", "endMillis"))
        if (
            not all(type(value) is int for value in (cue, start, end))
            or cue <= 0 or cue in cues or not 0 <= start < end <= duration
        ):
            raise ValueError("Invalid or duplicate cue window")
        cues.add(cue)
        clip = clips / f"{cue}.wav"
        if clip.is_symlink() or not clip.is_file():
            raise ValueError(f"Missing synthesized WAV for cue {cue}")
        inputs.extend(["-f", "wav", "-i", str(clip.resolve())])
        start_samples = start * (SAMPLE_RATE // 1000)
        window_samples = (end - start) * (SAMPLE_RATE // 1000)
        filters.append(
            f"[{index}:a]aresample={SAMPLE_RATE},aformat=channel_layouts=mono,"
            f"atrim=end_sample={window_samples},asetpts=PTS-STARTPTS,"
            f"adelay={start_samples}S[cue{index}]"
        )

    labels = "".join(f"[cue{index}]" for index in range(len(segments)))
    length = duration * (SAMPLE_RATE // 1000)
    filters.append(
        f"{labels}amix=inputs={len(segments)}:normalize=0,"
        f"alimiter=limit=0.95:level=0:latency=1,"
        f"apad=whole_len={length},atrim=end_sample={length}[voice]"
    )
    with tempfile.TemporaryDirectory(dir=output.parent) as pending:
        rendered = Path(pending) / "voiceover.wav"
        subprocess.run(
            [
                "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
                *inputs, "-filter_complex", ";".join(filters), "-map", "[voice]",
                "-c:a", "pcm_s16le", "-rf64", "auto", str(rendered),
            ],
            check=True,
        )
        if video is not None:
            dubbed = Path(pending) / "dubbed.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
                    "-f", "mov", "-i", str(video.resolve()), "-f", "wav", "-i", str(rendered),
                    "-map", "0:V:0", "-map", "1:a:0", "-map", "0:a?",
                    "-c", "copy", "-c:a:0", "aac", "-b:a:0", "160k",
                    "-disposition:a", "0", "-disposition:a:0", "default",
                    "-movflags", "+faststart", str(dubbed),
                ],
                check=True,
            )
            rendered = dubbed
        output.hardlink_to(rendered)


def verify_video_duration(video, duration):
    if video.suffix.lower() != ".mp4" or video.is_symlink() or not video.is_file():
        raise ValueError("Expected an existing MP4 video")
    probe = subprocess.run(
        [
            "ffprobe", "-v", "error", "-f", "mov", "-select_streams", "V:0",
            "-show_entries", "stream=duration", "-of", "csv=p=0", str(video.resolve()),
        ],
        check=True, capture_output=True, text=True,
    )
    try:
        millis = Decimal(probe.stdout.strip()) * 1000
    except InvalidOperation as error:
        raise ValueError("Could not determine the video stream duration") from error
    if not millis.is_finite() or abs(millis - duration) > 1:
        raise ValueError("Voiceover duration does not match the video stream")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("clips", type=Path, help="directory containing <cue>.wav files")
    parser.add_argument("output", type=Path)
    parser.add_argument("--video", type=Path, help="source MP4 for dubbed video output")
    args = parser.parse_args()
    try:
        with args.plan.open("rb") as source:
            data = source.read(64 * 1024 + 1)
        if len(data) > 64 * 1024:
            raise ValueError("Speech plan exceeds 64 KiB")
        render_voiceover(json.loads(data), args.clips, args.output, args.video)
    except (OSError, ValueError, KeyError, TypeError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
