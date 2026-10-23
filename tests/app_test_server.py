"""A small Bob stand-in for testing the Bob app (Dart) against the real Python server code.

Starts the real StreamServer (HTTPS, pairing, the version-1 API) with a pretend controller, and talks to the test over stdin and
stdout, one JSON object per line:

    stdout  {"ready": true, "https_port": 8443, "fingerprint": "..."}        when it is up
    stdin   code     ->  stdout {"code": "K7PQ-2M9X-4TWD"}                  a fresh pairing code
    stdin   handled  ->  stdout {"handled": [["/say hi", "app:Test Mac"]], "moves": [[0.5, 0.5]]}
    stdin   quit     ->  exits
"""
import json
import sys
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402
import stream  # noqa: E402
from appapi import show_code  # noqa: E402


class FakeController:
    def __init__(self):
        self.cfg = SimpleNamespace(radio=SimpleNamespace(name="TestBob"))
        self.handled, self.moves = [], []
        self.drive = SimpleNamespace(stop=lambda: self.moves.append("stop"))

    def handle(self, line, by=None, role="owner"):
        self.handled.append([line, by])
        return f"did {line}"

    def manual(self, left, right, seconds):
        self.moves.append([left, right])
        return "moved"


def main() -> None:
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.mkdtemp())
    cfg = config.StreamConfig()
    cfg.host, cfg.port, cfg.https_port, cfg.bonjour = "127.0.0.1", 0, 0, False
    count = [0]

    def picture() -> bytes:                               # a different picture every time, as a real camera gives
        count[0] += 1
        return b"\xff\xd8" + f"jpeg-{count[0]}-".encode() * 50 + b"\xff\xd9"

    srv = stream.StreamServer(cfg, SimpleNamespace(capture_jpeg=picture), base=base)
    ctrl = FakeController()
    srv.controller = ctrl
    srv.status = lambda: {"mode": "AUTO", "thinking": False, "camera": "on", "mic": "off", "muted": False, "cap": 0.8,
                          "cost": 0.1, "model": "sonnet-5-5", "effort": "low", "version": "test", "rooms": ["Kitchen"],
                          "usage": {"today": 0.5, "all": 3.25, "since": "2026-10-20"}, "events": [], "log": []}
    srv.hub.interval = 0.05
    stream.RECHECK_S = 0.2
    srv.start()
    print(json.dumps({"ready": True, "https_port": srv._httpsd.server_address[1], "fingerprint": srv.fingerprint}), flush=True)
    for line in sys.stdin:
        word = line.strip()
        if word == "code":
            print(json.dumps({"code": show_code(srv.pairing.new_code("test"))}), flush=True)
        elif word == "handled":
            print(json.dumps({"handled": ctrl.handled, "moves": ctrl.moves}), flush=True)
        elif word == "quit":
            break
    srv.stop()


if __name__ == "__main__":
    threading.current_thread().name = "main"
    main()
