#!/usr/bin/env python3
"""Translate one verified subtitle output using a local translation adapter."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import sys

MAX_ACTION_INPUT = 60 * 1024


def bundled_translator(editor, plugin_id):
    if not re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", plugin_id):
        raise ValueError("Invalid translator plugin ID")
    catalog = editor("plugin-catalog")
    selected = next((plugin for plugin in catalog if plugin["bundled"]
                     and plugin["manifest"]["id"] == plugin_id
                     and "subtitle-translation" in plugin["manifest"]["capabilities"]), None)
    if selected is None:
        raise ValueError("Selected plugin does not provide bundled subtitle translation")
    root = Path(os.environ.get("ARRUMO_PLUGIN_SOURCE_ROOT", Path(__file__).resolve().parents[2]))
    script = root / plugin_id / "tools" / "translate-subtitles.py"
    return [sys.executable, script.resolve(strict=True)]


def translate_track(editor, scope, language, translator, expected_revision=0):
    workspace, _, format_id = scope

    def action(name, payload):
        data = json.dumps(payload, ensure_ascii=False)
        if len(data.encode("utf-8")) > MAX_ACTION_INPUT:
            raise ValueError("Subtitle action input exceeds 60 KiB")
        response = editor("invoke-plugin-action", "auto-dubbing", name, workspace, data=data)
        if not response.get("ok"):
            raise ValueError(f"Auto-Dubbing rejected {name}: {response.get('error', 'unknown error')}")
        return response["result"]

    language = language.lower()
    if len(language) > 63 or not re.fullmatch(r"[a-z]{2,8}(?:-[a-z0-9]{1,8})*", language):
        raise ValueError("Invalid subtitle language tag")
    if expected_revision < 0:
        raise ValueError("Expected revision must be zero or greater")

    known = editor("completed-subtitle-languages", *scope)
    current = editor("completed-subtitle-track", *scope, language)["revision"] if language in known else 0
    if current != expected_revision:
        raise ValueError("Translated subtitle revision differs from the expected revision")

    source = editor("completed-subtitles", *scope)
    cues = action("read-subtitle-cues", {"subtitles": source["subtitles"]})["cues"]
    request = json.dumps({"targetLanguage": language, "cues": cues}, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryFile() as output:
        subprocess.run(
            translator, input=request, stdout=output,
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
        revision = editor("revise-completed-subtitle-track", *scope, language, expected_revision, file)
    return {"formatId": format_id, "language": language, "sourceRevision": source["revision"], "revision": revision}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("editor", type=Path, help="path to arrumo-workspaces")
    parser.add_argument("database", type=Path)
    parser.add_argument("workspace", type=int)
    parser.add_argument("run", type=int)
    parser.add_argument("format", type=int)
    parser.add_argument("language")
    adapter = parser.add_mutually_exclusive_group(required=True)
    adapter.add_argument("translator", type=Path, nargs="?", help="local executable accepting cue JSON on stdin")
    adapter.add_argument("--translator-plugin", help="bundled translator ID resolved from local plugin checkouts")
    parser.add_argument("--expected-revision", type=int, default=0)
    args = parser.parse_args()

    def editor(operation, *arguments, data=None):
        result = subprocess.run(
            [args.editor, args.database, operation, *map(str, arguments)],
            input=data, stdout=subprocess.PIPE, encoding="utf-8", check=True,
        )
        return json.loads(result.stdout) if result.stdout else None

    try:
        translator = (bundled_translator(editor, args.translator_plugin) if args.translator_plugin
                      else [args.translator.resolve(strict=True)])
        print(json.dumps(translate_track(
            editor, (args.workspace, args.run, args.format), args.language,
            translator, args.expected_revision,
        )))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
