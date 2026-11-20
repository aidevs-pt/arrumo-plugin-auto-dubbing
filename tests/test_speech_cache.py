import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


TOOLS = Path(__file__).resolve().parents[1] / "tools"
LOCK_SCRIPT = """
from pathlib import Path
import runpy
import sys
sys.path.insert(0, sys.argv[1])
lock = runpy.run_path(str(Path(sys.argv[1]) / "speech_cache.py"))["speech_clip_lock"]
with lock(Path(sys.argv[2]), timeout=0.2):
    print("locked", flush=True)
    sys.stdin.read()
"""


class SpeechCacheTest(unittest.TestCase):
    def test_other_process_waits_and_lock_releases_when_owner_exits(self):
        with tempfile.TemporaryDirectory() as root:
            command = [sys.executable, "-B", "-c", LOCK_SCRIPT, TOOLS, Path(root) / "clip.wav"]
            owner = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            try:
                self.assertEqual(owner.stdout.readline().strip(), "locked")
                contender = subprocess.run(command, input="", text=True, capture_output=True, timeout=5)
                self.assertNotEqual(contender.returncode, 0)
                self.assertIn("Timed out waiting for cached speech synthesis", contender.stderr)
            finally:
                owner.communicate(input="", timeout=5)

            contender = subprocess.run(command, input="", text=True, capture_output=True, timeout=5)
            self.assertEqual(contender.returncode, 0, contender.stderr)
            self.assertEqual(contender.stdout.strip(), "locked")

    def test_prune_preserves_active_and_unrecognized_files(self):
        with tempfile.TemporaryDirectory() as root:
            cache = Path(root)
            old, active, recent = (cache / f"{char * 64}.wav" for char in "abc")
            for path, stamp in [(old, 1), (active, 2), (recent, 3)]:
                path.write_bytes(b"clip")
                os.utime(path, (stamp, stamp))
            unrelated = cache / "manual.wav"
            unrelated.write_bytes(b"unrelated")
            command = [sys.executable, "-B", TOOLS / "prune-speech-cache.py", cache, "--max-bytes", "4"]
            preview = json.loads(subprocess.check_output([*command, "--dry-run"], text=True))
            self.assertEqual((preview["clipsSelected"], preview["bytesSelected"]), (2, 8))
            self.assertTrue(old.exists() and active.exists() and recent.exists())
            self.assertFalse(list(cache.glob("*.lock")))

            owner = subprocess.Popen(
                [sys.executable, "-B", "-c", LOCK_SCRIPT, TOOLS, active],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            )
            try:
                self.assertEqual(owner.stdout.readline().strip(), "locked")
                pruned = json.loads(subprocess.check_output(command, text=True))
                self.assertEqual((pruned["clipsSelected"], pruned["clipsSkipped"]), (2, 1))
                self.assertFalse(old.exists() or recent.exists())
                self.assertTrue(active.exists() and unrelated.exists())
            finally:
                owner.communicate(input="", timeout=5)
            pruned = json.loads(subprocess.check_output(
                [sys.executable, "-B", TOOLS / "prune-speech-cache.py", cache, "--max-age-days", "1"],
                text=True,
            ))
            self.assertEqual(pruned["clipsSelected"], 1)
            self.assertFalse(active.exists())
            self.assertTrue(unrelated.exists())
