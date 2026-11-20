#!/usr/bin/env python3
"""Translate one verified subtitle output using a local translation adapter."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import tempfile

MAX_ACTION_INPUT = 60 * 1024


def translate(args):
    def editor(operation, *arguments, data=None):
        result = subprocess.run(
            [args.editor, args.database, operation, *map(str, arguments)],
            input=data, stdout=subprocess.PIPE, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout) if result.stdout else None

    def action(name, payload):
        data = json.dumps(payload, ensure_ascii=False)
        if len(data.encode("utf-8")) > MAX_ACTION_INPUT:
            raise ValueError("Subtitle action input exceeds 60 KiB")
        response = editor("invoke-plugin-action", "auto-dubbing", name, args.workspace, data=data)
        if not response.get("ok"):
            raise ValueError(f"Auto-Dubbing rejected {name}: {response.get('error', 'unknown error')}")
        return response["result"]

    language = args.language.lower()
    if len(language) > 63 or not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", language):
        raise ValueError("Invalid subtitle language tag")
    if args.expected_revision < 0:
        raise ValueError("Expected revision must be zero or greater")

    scope = (args.workspace, args.run, args.format)
    known = editor("completed-subtitle-languages", *scope)
    current = editor("completed-subtitle-track", *scope, language)["revision"] if language in known else 0
    if current != args.expected_revision:
        raise ValueError("Translated subtitle revision differs from the expected revision")

    source = editor("completed-subtitles", *scope)
    cues = action("read-subtitle-cues", {"subtitles": source["subtitles"]})["cues"]
    request = json.dumps({"targetLanguage": language, "cues": cues}, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            [args.translator.resolve(strict=True)], input=request, stdout=output,
            check=True, timeout=120,
        )
        output.seek(0)
        data = output.read(MAX_ACTION_INPUT + 1)
    if len(data) > MAX_ACTION_INPUT:
        raise ValueError("Translator output exceeds 60 KiB")
    translations = json.loads(data)["translations"]
    result = action("assemble-translated-subtitles", {
        "subtitles": source["subtitles"], "translations": translations,
    })
    with tempfile.TemporaryDirectory(prefix="arrumo-subtitles-") as temporary:
        file = Path(temporary) / "translated.srt"
        file.write_bytes(result["subtitles"].encode("utf-8"))
        revision = editor("revise-completed-subtitle-track", *scope, language, args.expected_revision, file)
    return {"formatId": args.format, "language": language, "sourceRevision": source["revision"], "revision": revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editor", type=Path, help="path to arrumo-workspaces")
    parser.add_argument("database", type=Path)
    parser.add_argument("workspace", type=int)
    parser.add_argument("run", type=int)
    parser.add_argument("format", type=int)
    parser.add_argument("language")
    parser.add_argument("translator", type=Path, help="local executable accepting cue JSON on stdin")
    parser.add_argument("--expected-revision", type=int, default=0)
    try:
        print(json.dumps(translate(parser.parse_args())))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
