#!/usr/bin/env python3
"""Render a planned dub from local media mounted by the isolated SDK worker."""
import json
from pathlib import Path

from voiceover import render_voiceover


def main():
    inputs = Path("/media")
    output = Path("/output")
    with (inputs / "plan.json").open("rb") as stream:
        data = stream.read(64 * 1024 + 1)
    if len(data) > 64 * 1024:
        raise ValueError("Speech plan exceeds 64 KiB")
    name = "dubbed.mp4"
    render_voiceover(json.loads(data), inputs, output / name, inputs / "source.mp4")
    (output / "result.json").write_text(json.dumps({"file": name}), encoding="utf-8")


if __name__ == "__main__":
    main()
