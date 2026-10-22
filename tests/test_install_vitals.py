"""install_vitals.sh: the recorder script it writes is run once with pretend system tools; the installer is syntax-checked."""
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INSTALLER = ROOT / "install_vitals.sh"

STUBS = {
    "ip": 'echo "default via 192.168.1.1 dev wlan0"',
    "ping": 'exit "${PING_EXIT:-0}"',
    "free": 'printf "              total        used        free      shared  buff/cache   available\\nMem:           3900         233        2500          10        1100        3500\\n"',
    "vcgencmd": 'case "$1" in measure_temp) echo "temp=44.8\'C";; get_throttled) echo "throttled=0x0";; esac',
    "iw": 'echo "	signal: -55 dBm"',
    "pgrep": 'echo 1',
}


class VitalsTests(unittest.TestCase):
    def one_line(self, ping_exit="0"):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        t = Path(tmp.name)
        (t / "bin").mkdir()
        for name, body in STUBS.items():
            p = t / "bin" / name
            p.write_text(f"#!/usr/bin/env bash\n{body}\n")
            p.chmod(0o755)
        script = re.search(r"<<'EOS'\n(#!/usr/bin/env bash\n.*?)\nEOS\n", INSTALLER.read_text(), re.S).group(1)
        log = t / "vitals.log"
        (t / "run.sh").write_text(script.replace("/var/log/bob-vitals.log", str(log)))
        # 'sleep' becomes a function that ends the shell, so exactly one pass of the loop runs
        subprocess.run(["bash", "-c", f'sleep() {{ exit 0; }}; export PATH="{t}/bin:$PATH" PING_EXIT={ping_exit}; . {t}/run.sh'],
                       check=True, timeout=20)
        return log.read_text().strip()

    def test_one_line_has_everything_needed_after_a_crash(self):
        line = self.one_line()
        for part in ("load=", "mem_used=233MB", "avail=3500MB", "temp=44.8'C", "throttled=0x0", "wifi=-55dBm",
                     "router-ok", "bob=1", "up="):
            self.assertIn(part, line)

    def test_an_unreachable_router_is_flagged_loudly(self):
        self.assertIn("ROUTER-UNREACHABLE", self.one_line(ping_exit="1"))

    def test_the_installer_is_valid_shell_and_has_help(self):
        subprocess.run(["bash", "-n", str(INSTALLER)], check=True)
        out = subprocess.run(["bash", str(INSTALLER), "--help"], capture_output=True, text=True, check=True).stdout
        self.assertIn("--watchdog", out)
        self.assertIn("--undo", out)

    def test_an_unknown_option_is_refused_before_anything_is_changed(self):
        done = subprocess.run(["bash", str(INSTALLER), "--nonsense"], capture_output=True, text=True)
        self.assertEqual(done.returncode, 2)


if __name__ == "__main__":
    unittest.main()
