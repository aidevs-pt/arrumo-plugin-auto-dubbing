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

    def test_mux_preserves_picture_and_original_audio(self):
        tool = Path(__file__).resolve().parents[1] / "tools" / "render-voiceover.py"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.mp4"
            subprocess.run([
                "ffmpeg", "-v", "error",
                "-f", "lavfi", "-i", "color=c=blue:s=64x64:r=25:d=1",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=1",
                "-c:v", "mpeg4", "-c:a", "aac", str(source),
            ], check=True)
            original = source.read_bytes()
            with wave.open(str(root / "1.wav"), "wb") as clip:
                clip.setparams((1, 2, 48000, 0, "NONE", "not compressed"))
                clip.writeframes(array.array("h", [5000]) * 4800)
            plan = root / "plan.json"
            output = root / "dubbed.mp4"
            command = [sys.executable, tool, plan, root, output, "--video", source]
            data = {"durationMillis": 900, "segments": [{
                "cue": 1, "startMillis": 200, "endMillis": 400,
            }]}
            plan.write_text(json.dumps(data), encoding="utf-8")
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)
            self.assertFalse(output.exists())
            data["durationMillis"] = 1000
            plan.write_text(json.dumps(data), encoding="utf-8")
            subprocess.run(command, check=True, capture_output=True)
            streams = json.loads(subprocess.check_output([
                "ffprobe", "-v", "error", "-show_streams", "-of", "json", output,
            ]))["streams"]
            self.assertEqual([stream["codec_type"] for stream in streams], ["video", "audio", "audio"])
            self.assertEqual([stream["disposition"]["default"] for stream in streams[1:]], [1, 0])
            self.assertEqual(float(streams[0]["duration"]), 1.0)
            for source_track, output_track in [("0:v:0", "0:v:0"), ("0:a:0", "0:a:1")]:
                def packet_hash(path, track):
                    return subprocess.check_output([
                        "ffmpeg", "-v", "error", "-i", path,
                        "-map", track, "-c", "copy", "-f", "hash", "-",
                    ])
                self.assertEqual(packet_hash(source, source_track), packet_hash(output, output_track))
            self.assertEqual(source.read_bytes(), original)
