import subprocess
import sys
import textwrap
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
from listen import Listener  # noqa: E402

# A stand-in for arecord: on SIGTERM it prints the complaint newer alsa-utils prints, then exits with code 1.
ARECORD_LIKE = textwrap.dedent("""
    import signal, sys, time
    def stop(*a):
        sys.stderr.write("arecord: pcm_read:2272: read error: Interrupted system call\\n")
        sys.exit(1)
    signal.signal(signal.SIGTERM, stop)
    print("ready", file=sys.stderr, flush=True)
    time.sleep(30)
""")
DIES_BY_ITSELF = "import sys; sys.stderr.write('arecord: main:850: audio open error: Device or resource busy\\n'); sys.exit(1)"


def listener():
    return Listener(config.MicConfig(), lambda t: None, SimpleNamespace(), SimpleNamespace())


def spawn(code):
    return subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, stderr=subprocess.PIPE)


class StopTests(unittest.TestCase):
    def test_ending_the_recording_ourselves_is_not_a_microphone_problem(self):
        mic = listener()
        proc = mic._proc = spawn(ARECORD_LIKE)
        time.sleep(0.8)                                    # let it install its signal handler
        self.assertEqual(mic._finish_proc(proc), "")

    def test_stopped_from_another_thread_before_the_listener_looks(self):
        """The Tab key stops the recorder; it complains and exits before the listener thread gets to check."""
        mic = listener()
        proc = mic._proc = spawn(ARECORD_LIKE)
        time.sleep(0.8)
        mic._stop_proc()                                   # what pressing Tab again does
        proc.wait(5)                                       # it is already gone when the listener thread arrives
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(mic._finish_proc(proc), "")

    def test_a_real_failure_is_still_reported(self):
        mic = listener()
        proc = mic._proc = spawn(DIES_BY_ITSELF)
        time.sleep(0.8)                                    # it has already died on its own
        self.assertIn("Device or resource busy", mic._finish_proc(proc))

    def test_a_plain_terminate_is_fine_too(self):
        mic = listener()
        proc = mic._proc = spawn("import time; time.sleep(30)")
        time.sleep(0.3)
        self.assertEqual(mic._finish_proc(proc), "")


if __name__ == "__main__":
    unittest.main()
