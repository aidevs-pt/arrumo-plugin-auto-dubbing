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
lock = runpy.run_path(str(Path(sys.argv[1]) / "dub-completed-output.py"))["speech_clip_lock"]
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
