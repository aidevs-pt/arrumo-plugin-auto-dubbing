import array
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import wave


class VoiceoverTest(unittest.TestCase):
    def test_places_and_trims_overlapping_cues_and_preserves_existing_output(self):
        tool = Path(__file__).resolve().parents[1] / "tools" / "render-voiceover.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for cue, level, duration in [(1, 3000, 700), (2, 4500, 150)]:
                with wave.open(str(root / f"{cue}.wav"), "wb") as clip:
                    clip.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                    clip.writeframes(array.array("h", [level]) * (duration * 48))
            plan = root / "plan.json"
            plan.write_text(json.dumps({
                "durationMillis": 1000,
                "segments": [
                    {"cue": 1, "startMillis": 100, "endMillis": 400},
                    {"cue": 2, "startMillis": 300, "endMillis": 600},
                ],
            }), encoding="utf-8")
            output = root / "voiceover.wav"
            command = [sys.executable, tool, plan, root, output]
            subprocess.run(command, check=True, capture_output=True)
            with wave.open(str(output), "rb") as result:
                self.assertEqual((result.getframerate(), result.getnchannels(), result.getnframes()),
                                 (48000, 1, 48000))
                samples = array.array("h", result.readframes(48000))
            for millis, level in [(99, 0), (100, 3000), (300, 7500), (400, 4500), (450, 0), (999, 0)]:
                self.assertAlmostEqual(samples[millis * 48], level, delta=1)
            original = output.read_bytes()
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertEqual(output.read_bytes(), original)
