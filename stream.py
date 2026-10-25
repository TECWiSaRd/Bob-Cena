"""MJPEG camera stream served from the Pi (stdlib only).

    http://<pi-ip>:8080/            viewer page
    http://<pi-ip>:8080/stream      raw MJPEG (works in <img>, VLC, ffplay)
    http://<pi-ip>:8080/snapshot.jpg  single frame

Respects the console's /camera off switch. If BOB_STREAM_TOKEN is set in .env,
every request must carry ?token=<value>.
"""
from __future__ import annotations

import json
import select
import socket
import logging
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlparse

import ssl
from pathlib import Path

import appapi
from access import AccessPolicy, Lockout
from version import __version__

log = logging.getLogger("bob.stream")

PAGE = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width">
<title>Bob's eye</title>
<style>body{margin:0;background:#111;color:#ccc;font:14px system-ui;text-align:center}
img{max-width:100%%;height:auto}p{margin:.5em}</style>
<p>Bob's camera</p><img src="stream%(q)s" alt="camera stream (blank if the camera is off)">
"""


# Commands the dashboard may run (the first word, without the slash). Anything else is refused:
# no /quit, /forget, /people clear, /calibrate (it drives the robot for a long time) and so on.
RECHECK_S = 5.0      # a running video stream re-checks its token this often (Bob may have moved to another Wi-Fi)
DASH_COMMANDS = {"estop", "clear", "pause", "hush", "resume", "step", "ask", "motion", "camera", "mute", "unmute",
                 "follow", "find", "check", "radio", "listen", "range", "speed", "goal", "say", "sound", "talk", "trim", "music", "shutdown", "usage", "sleep"}

DASH_PAGE = """<!doctype html><html lang=en><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Bob</title>
<style>
:root{color-scheme:dark;--bg:#14161a;--card:#1d2026;--line:#2c313a;--text:#e8eaee;--dim:#98a1ae;--ok:#3ecf8e;--warn:#f5b942;--bad:#ff5d5d;--acc:#6aa8ff}
@media(prefers-color-scheme:light){:root{color-scheme:light;--bg:#f2f4f7;--card:#fff;--line:#d9dee6;--text:#16191f;--dim:#5b6573;--ok:#14935b;--warn:#a96a00;--bad:#d62f2f;--acc:#1f5fd1}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:15px system-ui,sans-serif;padding:12px 16px calc(12px + env(safe-area-inset-bottom))}
main{max-width:640px;margin:auto;display:grid;gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px}
h1{font-size:18px;margin:0 0 4px}.row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1}
.chip{font-size:12px;padding:3px 8px;border-radius:99px;border:1px solid var(--line);color:var(--dim);white-space:nowrap}
.chip.ok{color:var(--ok)}.chip.warn{color:var(--warn)}.chip.bad{color:var(--bad);border-color:var(--bad)}
button{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px 8px;min-height:44px;touch-action:manipulation}
button:active{background:var(--line)}#estop{background:var(--bad);color:#fff;border:0;font-weight:700;font-size:18px;min-height:56px}
img{width:100%;border-radius:8px;background:#000;display:block}
.pad{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;max-width:300px;margin:auto}.pad button{min-height:56px;user-select:none;-webkit-user-select:none}
input{font:inherit;color:var(--text);background:var(--bg);border:1px solid var(--line);border-radius:10px;padding:12px;width:100%;min-height:44px}
pre{margin:0;max-height:240px;overflow:auto;font:12px/1.45 ui-monospace,monospace;white-space:pre-wrap;word-break:break-word}
.l-WARNING{color:var(--warn)}.l-ERROR{color:var(--bad)}.t-BOB,.t-SAY{color:var(--acc)}.t-RADIO{color:var(--ok)}.t-HEARD,.t-YOU{color:#c68cff}
small{color:var(--dim)}
</style>
<main>
 <div class=card><h1>Bob <span id=mode class=chip>...</span></h1><div class=row id=chips></div></div>
 <button id=estop>EMERGENCY STOP</button>
 <div class=card><img id=cam alt="camera (blank if the camera is off)"></div>
 <div class=card><div class=pad>
   <span></span><button data-d="1,1">&#9650;</button><span></span>
   <button data-d="-1,1">&#9664;</button><button data-d="0,0">&#9632;</button><button data-d="1,-1">&#9654;</button>
   <span></span><button data-d="-1,-1">&#9660;</button><span></span></div>
   <p style="text-align:center;margin:8px 0 0"><small>hold to drive: the wheels stop as soon as you let go</small></p></div>
 <div class="card row">
  <button data-c="pause">Pause AI</button><button data-c="resume">Resume AI</button><button data-c="clear">Clear E-stop</button>
  <button data-c="follow 30">Follow me</button><button data-c="follow off">Stop following</button>
  <button data-c="mute">Mute</button><button data-c="unmute">Unmute</button>
  <button data-c="camera on">Camera on</button><button data-c="camera off">Camera off</button>
  <button data-c="sleep on">Sleep</button><button data-c="sleep off">Wake up</button></div>
 <div class=card id=roomcard style="display:none"><b>Go to a room</b> <small id=roomnow></small>
  <div class=row style="margin-top:8px"><select id=roomsel></select><button id=goroom style="flex:0 0 90px">Go</button><button id=stoproom style="flex:0 0 90px">Stop</button></div>
  <small>He turns to find the room's tag, then drives up to it. Hold the emergency stop button to cancel.</small></div>
 <div class=card id=musiccard style="display:none"><b>Music</b> <small id=musictext></small>
  <div class=row style="margin-top:8px">
   <button data-c="music prev">&#9198;</button><button data-c="music play">&#9654;</button><button data-c="music pause">&#9208;</button><button data-c="music next">&#9197;</button>
   <button data-c="music vol down">Vol &minus;</button><button data-c="music vol up">Vol +</button></div></div>
 <div class=card><form id=say class=row><input id=msg placeholder="Say something to Bob (or a /command)" autocomplete=off><button style="flex:0 0 80px">Send</button></form></div>
 <div class=card><b>Log</b><pre id=log></pre></div>
 <div class=card id=eventscard style="display:none"><b>Recent events</b><pre id=events></pre></div>
 <div class=card><small id=foot></small></div>
 <div class=card id=powercard style="display:none"><button id=poweroff style="width:100%">Shut down the Pi</button>
  <p style="margin:8px 0 0"><small>Bob stops, says goodbye, and the Pi powers off. It can't be switched back on from here: someone has to unplug and replug the power.</small></p></div>
</main>
<script>
const tok=new URLSearchParams(location.search).get('token')||'';
const q=p=>p+'?token='+encodeURIComponent(tok);
document.getElementById('cam').src=q('stream');
const $=id=>document.getElementById(id);
async function post(path,body){const r=await fetch(q(path),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});return r.json().catch(()=>({}))}
async function cmd(c){const r=await post('api/cmd',{cmd:c});if(r.output){note(r.output)}}
function note(t){const p=$('log');p.append(document.createTextNode('> '+t+'\\n'));p.scrollTop=p.scrollHeight}
$('estop').onclick=()=>cmd('/estop');
$('goroom').onclick=()=>{const r=$('roomsel').value;if(r)cmd('/goto '+r)};$('stoproom').onclick=()=>cmd('/goto stop');
$('poweroff').onclick=async()=>{if(!confirm('Shut down the Pi? It cannot be switched back on from here: someone has to unplug and replug the power.'))return;await cmd('/shutdown');await cmd('/shutdown confirm')};
document.querySelectorAll('[data-c]').forEach(b=>b.onclick=()=>cmd('/'+b.dataset.c));
$('say').onsubmit=e=>{e.preventDefault();const v=$('msg').value.trim();if(v){$('msg').value='';cmd(v.startsWith('/')?v:'/ask '+v)}};
let timer=null;
function drive(l,r){post('api/drive',{left:l,right:r})}
document.querySelectorAll('[data-d]').forEach(b=>{
 const [l,r]=b.dataset.d.split(',').map(Number);
 const go=e=>{e.preventDefault();if(timer)clearInterval(timer);drive(l,r);if(l||r)timer=setInterval(()=>drive(l,r),250)};
 const end=()=>{if(timer){clearInterval(timer);timer=null;drive(0,0)}};
 b.addEventListener('pointerdown',go);['pointerup','pointercancel','pointerleave'].forEach(n=>b.addEventListener(n,end));});
addEventListener('blur',()=>{if(timer){clearInterval(timer);timer=null;drive(0,0)}});
let shown=0;
async function poll(){try{
 const s=await (await fetch(q('api/status'))).json();
 $('powercard').style.display=s.power?'':'none';$('musiccard').style.display=s.music_enabled?'':'none';$('musictext').textContent=s.music||'';
 const m=$('mode');m.textContent=s.mode;m.className='chip '+(s.mode==='E-STOP'?'bad':s.mode==='AUTO'?'ok':'warn');
 const chips=[['AI '+(s.thinking?'thinking':'idle')],['camera '+s.camera,s.camera==='OFF'?'warn':''],['mic '+s.mic],['audio '+(s.muted?'MUTED':'on'),s.muted?'warn':''],
  ['cap '+s.cap],s.radio?['radio '+s.radio,s.radio==='connected'?'ok':'']:null,s.dist!=null?['dist '+s.dist+' cm',s.dist<20?'bad':'']:null,
  s.follow?['FOLLOWING','ok']:null,s.calibrating?['CALIBRATING','warn']:null,s.sleep?['sleeping','warn']:null,[s.model+' / '+s.effort],['$'+s.cost.toFixed(3)+' this run'],
  s.usage&&s.usage.all!=null?['today $'+s.usage.today.toFixed(2)+' · all $'+s.usage.all.toFixed(2)]:null,
  s.vitals&&s.vitals.temp_c!=null?[Math.round(s.vitals.temp_c)+' °C',s.vitals.temp_c>=80?'bad':s.vitals.temp_c>=70?'warn':'']:null,
  s.vitals&&s.vitals.load!=null?['load '+s.vitals.load.toFixed(1),s.vitals.load>3.5?'warn':'']:null,
  s.vitals&&s.vitals.throttled&(5)?['power/heat limit','bad']:null,s.room?['in the '+s.room]:null].filter(Boolean);
 const rc=$('roomcard');rc.style.display=(s.rooms&&s.rooms.length)?'':'none';
 if(s.rooms&&s.rooms.join()!==$('roomsel').dataset.k){$('roomsel').dataset.k=s.rooms.join();$('roomsel').replaceChildren(...s.rooms.map(r=>{const o=document.createElement('option');o.textContent=r;return o}))}
 $('roomnow').textContent=s.room?'(now in the '+s.room+')':'';
 const ev=s.events||[];$('eventscard').style.display=ev.length?'':'none';
 $('events').textContent=ev.map(e=>e.t.slice(11,19)+' '+e.kind+' '+e.text).join('\\n');
 $('foot').textContent='Bob '+s.version;
 $('chips').replaceChildren(...chips.map(([t,c])=>{const e=document.createElement('span');e.className='chip '+(c||'');e.textContent=t;return e}));
 const p=$('log');const stick=p.scrollTop+p.clientHeight>=p.scrollHeight-30;
 p.replaceChildren(...s.log.map(x=>{const e=document.createElement('div');e.className='l-'+x.l+' t-'+x.t;e.textContent=x.m;return e}));
 if(stick)p.scrollTop=p.scrollHeight;
}catch(e){}}
poll();setInterval(poll,1000);
</script></html>"""


class FrameHub:
    """Shares captures between viewers and the brain so many viewers cost one camera read."""

    def __init__(self, camera, fps: float):
        self.camera, self.interval = camera, 1.0 / fps
        self._lock = threading.Lock()
        self._frame: bytes | None = None
        self._ts = 0.0

    def get(self) -> bytes | None:
        with self._lock:
            now = time.monotonic()
            if now - self._ts >= self.interval:
                self._frame = self.camera.capture_jpeg()
                self._ts = now
            return self._frame


class StreamServer:
    def __init__(self, cfg, camera, policy: AccessPolicy | None = None, base=None):
        self.cfg = cfg
        self.hub = FrameHub(camera, cfg.fps)
        # Who may get in: the owner's BOB_STREAM_TOKEN plus any per-person, per-Wi-Fi tokens (access.py)
        self.policy = policy or AccessPolicy(os.environ.get("BOB_STREAM_TOKEN", ""))
        self.lockout = Lockout()
        self._seen_users: dict[str, float] = {}
        self.clients = 0
        self._count_lock = threading.Lock()
        self._httpd = None
        self._httpsd = None
        self.base = base           # where certs/ and devices.json live (None = no HTTPS, e.g. in tests)
        self.version = __version__
        self.fingerprint = ""
        self.devices = appapi.DeviceStore(base / "devices.json" if base else None)
        self.pairing = None
        self.bonjour = None
        self._vitals: tuple[float, dict] = (0.0, {})
        self._events: tuple[float, list] = (0.0, [])
        self.controller = None     # set by attach(): the dashboard needs it
        self.logbuf = None

    def attach(self, controller, logbuf) -> None:
        self.controller, self.logbuf = controller, logbuf

    @property
    def dashboard_enabled(self) -> bool:
        return bool(self.cfg.dashboard and self.policy.can_run_dashboard() and self.controller is not None)

    @property
    def token(self) -> str:
        """The owner's token (kept for older code and tests)."""
        return self.policy.owner_token

    def status(self) -> dict:
        c = self.controller
        ctl = c.controls
        mode = ("E-STOP" if c.drive.estop.is_set() else "MANUAL" if c.drive_mode
                else "SLEEPING" if ctl.auto and c.sleep.asleep() else "AUTO" if ctl.auto else "PAUSED")
        lines = list(self.logbuf.lines)[-60:] if self.logbuf else []
        dist = c.ranger.distance_cm if c.ranger.enabled else None
        return {"mode": mode, "thinking": ctl.busy, "camera": "on" if c.camera.enabled else "OFF",
                "mic": c.listener.describe(), "muted": c.audio.muted, "cap": round(c.drive.speed_cap, 2),
                "radio": c.radio.state if c.radio else "", "dist": None if dist is None else round(dist),
                "follow": c.follower.active, "calibrating": bool(c.calibrating), "cost": ctl.cost,
                "power": bool(getattr(c, "power", None) and c.power.allows("dashboard")),
                "music_enabled": bool(c.music), "music": c.music.describe() if c.music else "",
                "model": c.cfg.brain.model.replace("claude-", ""), "effort": c.cfg.brain.effort,
                "auto": bool(ctl.auto), "going": bool(c.home.goer and c.home.goer.active),
                "operators": self._operators(c),
                "sleep": c.sleep.asleep(), "version": self.version, "usage": self._usage(c),
                "vitals": self._vitals_now(c), "events": self._events_now(c),
                "rooms": c.home.destinations(), "room": (c.home.where()[0] if c.home.active() else None),
                "log": [{"l": logging.getLevelName(lv), "t": tag, "m": line} for lv, tag, line in lines]}

    def _operators(self, c) -> list:
        """Who is using Bob right now: shared-console people, app devices used in the last two minutes, and web dashboard
        users seen in the last ten. Names only, never tokens."""
        out: list[dict] = []
        seen: set[str] = set()

        def add(name: str, via: str) -> None:
            key = name.lower()
            if key not in seen:
                seen.add(key)
                out.append({"name": name, "via": via})

        remote = getattr(c, "remote", None)
        for who in (remote.attached() if remote is not None else []):
            add(who["name"], "console" + (" (watching)" if who["role"] == "viewer" else ""))
        now = time.time()
        for name, info in self.devices.devices.items():
            if info.get("last_seen") and now - info["last_seen"] < 120:
                add(name, "app")
        mono = time.monotonic()
        for name, at in self._seen_users.items():
            if mono - at < 600:
                add(name, "dashboard")
        return out

    @staticmethod
    def _usage(c) -> dict:
        u = getattr(c.controls, "usage", None)
        if u is None:
            return {}
        from datetime import date
        today = date.today().isoformat()
        return {"today": round(u.total(today, today)["cost"], 4), "all": round(u.total()["cost"], 4), "since": u.since}

    def _vitals_now(self, c) -> dict:
        """The Pi's health numbers, looked up at most every 15 seconds (it runs small system commands)."""
        now = time.monotonic()
        if now - self._vitals[0] > 15:
            from alerts import vitals
            try:
                self._vitals = (now, vitals(self.base or "."))
            except Exception:
                self._vitals = (now, {})
        return self._vitals[1]

    def _events_now(self, c) -> list:
        now = time.monotonic()
        if now - self._events[0] > 5:
            rows = []
            tl = getattr(c, "timeline", None)
            if tl is not None and tl.enabled:
                for row in tl.recent(12):
                    rest = " ".join(f"{k}={v}" for k, v in row.items() if k not in ("t", "kind", "picture"))
                    rows.append({"t": row.get("t", ""), "kind": row.get("kind", "?"), "text": rest[:160]})
            self._events = (now, rows)
        return self._events[1]

    def note_user(self, name: str) -> None:
        """Log the first request from each person every 10 minutes, so the log shows who is using the dashboard."""
        now = time.monotonic()
        if now - self._seen_users.get(name, -1e9) > 600:
            self._seen_users[name] = now
            log.info("Dashboard: %s connected", name)

    def run_command(self, text: str, by: str | None = None) -> str:
        """Run a console command for the dashboard, but only from the allowed list."""
        text = str(text).strip()[:500]
        if not text:
            return ""
        if text.startswith("/"):
            name = text[1:].split(None, 1)[0].lower() if len(text) > 1 else ""
            if name not in DASH_COMMANDS:
                return f"/{name} isn't available from the dashboard"
        return self.controller.handle(text, by=by, role="dashboard") or ""

    def start(self) -> None:
        server = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 30   # a client that goes silent mid-request must not hold a thread forever

            def log_message(self, *args):  # keep the console clean
                pass

            @property
            def is_tls(self) -> bool:
                return isinstance(self.connection, ssl.SSLSocket)

            def _legacy_blocked(self) -> bool:
                """The browser pages and ?token= endpoints are for HTTP with a token. On the HTTPS port, with no token set,
                they would be open to the whole network, so only the app API is served there."""
                if self.is_tls and not server.policy.configured:
                    self._json({"error": "this port only serves the Bob app (/api/v1/...)"}, 403)
                    return True
                return False

            def _who(self, query, strong: bool) -> str | None:
                """The name of the person this request's token belongs to, or None after answering with an error."""
                ip = self.client_address[0]
                if server.lockout.blocked(ip):
                    self.close_connection = True
                    self._send(429, b"too many wrong tries: wait a minute", "text/plain")
                    return None
                name = server.policy.check(query.get("token", [""])[0], strong)
                if name is None:
                    server.lockout.failed(ip)
                    self._send(401, b"unauthorized", "text/plain")
                    return None
                server.note_user(name)
                return name

            def _authorized(self, query) -> bool:
                if not server.policy.configured:
                    return True
                self.user = self._who(query, strong=False)
                return self.user is not None

            def _dash_check(self, query) -> bool:
                """Dashboard requests need a proper token even more strictly: it can move the robot."""
                if not server.dashboard_enabled:
                    self._send(403, b"dashboard is off: set BOB_STREAM_TOKEN or a TOKEN_NAME (8+ characters) in .env", "text/plain")
                    return False
                self.user = self._who(query, strong=True)
                return self.user is not None

            def _json(self, obj, code=200):
                self._send(code, json.dumps(obj).encode(), "application/json")

            def do_POST(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.startswith("/api/v1/"):
                    return appapi.handle_v1(self, server, "POST", url, query)
                if not url.path.startswith("/api/"):
                    return self._send(404, b"not found", "text/plain")
                if self._legacy_blocked():
                    return
                if not self._dash_check(query):
                    return  # _dash_check already answered
                if "application/json" not in self.headers.get("Content-Type", ""):
                    return self._json({"error": "JSON only"}, 415)   # also blocks simple cross-site form posts
                try:
                    n = int(self.headers.get("Content-Length", ""))
                except ValueError:
                    self.close_connection = True
                    return self._json({"error": "Content-Length required"}, 411)
                if n < 0 or n > 4096:
                    self.close_connection = True   # the unread body would otherwise be parsed as the next request
                    return self._json({"error": "bad request size"}, 413 if n > 4096 else 400)
                try:
                    body = json.loads(self.rfile.read(n) or b"{}")
                    if not isinstance(body, dict):
                        raise ValueError("not an object")
                except (ValueError, TypeError):
                    return self._json({"error": "bad request"}, 400)
                try:
                    if url.path == "/api/cmd":
                        return self._json({"output": server.run_command(body.get("cmd", ""), by=self.user)})
                    if url.path == "/api/drive":
                        left = max(-1.0, min(1.0, float(body.get("left", 0))))
                        right = max(-1.0, min(1.0, float(body.get("right", 0))))
                        if left == 0 and right == 0:
                            server.controller.drive.stop()
                            return self._json({"output": ""})
                        return self._json({"output": server.controller.manual(left, right, 0.4)})
                except (ValueError, TypeError):
                    return self._json({"error": "bad request"}, 400)
                self._send(404, b"not found", "text/plain")

            def do_GET(self):
                url = urlparse(self.path)
                query = parse_qs(url.query)
                if url.path.startswith("/api/v1/"):
                    return appapi.handle_v1(self, server, "GET", url, query)
                if self._legacy_blocked():
                    return
                if url.path == "/dash":
                    if self._dash_check(query):
                        self._send(200, DASH_PAGE.encode(), "text/html; charset=utf-8")
                    return
                if url.path == "/api/status":
                    if self._dash_check(query):
                        self._json(server.status())
                    return
                if not self._authorized(query):
                    return self._send(401, b"unauthorized", "text/plain")
                if url.path in ("/", "/index.html"):
                    q = f"?token={quote(query['token'][0])}" if server.policy.configured else ""
                    return self._send(200, (PAGE % {"q": q}).encode(), "text/html; charset=utf-8")
                if url.path == "/snapshot.jpg":
                    frame = server.hub.get()
                    if frame is None:
                        return self._send(503, b"camera off or unavailable", "text/plain")
                    return self._send(200, frame, "image/jpeg")
                if url.path == "/stream":
                    return self._stream()
                self._send(404, b"not found", "text/plain")

            def _send(self, code, body, ctype):
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def _peer_gone(self) -> bool:
                """Has the browser hung up? (Writes only notice after a frame or two, and not at all if no frame is sent.)"""
                conn = self.connection
                if not isinstance(conn, socket.socket) or hasattr(conn, "pending"):
                    return False                    # TLS or an unusual socket: can't peek, so rely on write errors
                try:
                    ready, _, _ = select.select([conn], [], [], 0)
                    return bool(ready) and conn.recv(1, socket.MSG_PEEK) == b""
                except (BlockingIOError, InterruptedError):
                    return False                    # nothing to read right now: still connected
                except (OSError, ValueError):
                    return True                     # reset, or the socket is closed

            def _stream(self, still_ok=None):
                self.send_response(200)
                self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                with server._count_lock:
                    server.clients += 1
                    watching = server.clients
                log.info("stream viewer connected: %s (%d watching)", self.client_address[0], watching)
                last = None
                checked = time.monotonic()
                try:
                    while True:
                        if self._peer_gone():
                            break                  # a reload or closed tab: don't wait for a write to fail
                        if time.monotonic() - checked > RECHECK_S:
                            checked = time.monotonic()
                            if still_ok is not None:
                                if not still_ok():
                                    log.info("stream viewer dropped: their device was unpaired")
                                    break
                            elif server.policy.configured and getattr(self, "user", None) not in server.policy.valid():
                                log.info("stream viewer %s dropped: their token no longer works here", self.user)
                                break              # e.g. Bob moved to another Wi-Fi network
                        frame = server.hub.get()
                        if frame is None or frame is last:
                            time.sleep(server.hub.interval)
                            continue
                        last = frame
                        self.wfile.write(
                            b"--frame\r\nContent-Type: image/jpeg\r\nContent-Length: "
                            + str(len(frame)).encode() + b"\r\n\r\n" + frame + b"\r\n")
                        time.sleep(server.hub.interval)
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError, OSError):
                    pass
                finally:
                    self.close_connection = True      # the stream has no length, so ending it means hanging up
                    with server._count_lock:
                        server.clients -= 1
                        watching = server.clients
                    log.info("stream viewer left (%d watching)", watching)

        class Server(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                # called from inside socketserver's except block, so the active exception is the one to judge
                exc = sys.exc_info()[1]
                if exc is None:
                    return
                if isinstance(exc, (ConnectionResetError, BrokenPipeError, ConnectionAbortedError, ssl.SSLError, TimeoutError)):
                    # a browser dropping mid-request is routine; keep a trace for debugging
                    log.debug("stream client %s dropped: %r", client_address[0], exc)
                    return
                super().handle_error(request, client_address)

        class TlsServer(Server):
            """HTTPS. Each connection is wrapped here but its handshake happens in its own thread, so one slow or
            malicious client can never hold up the others."""
            context = None

            def get_request(self):
                sock, addr = super().get_request()
                return self.context.wrap_socket(sock, server_side=True, do_handshake_on_connect=False), addr

        host = self.cfg.host
        if not self.policy.configured and host not in ("127.0.0.1", "localhost", "::1"):
            # A camera must not be open to the whole network by accident: no password means this robot only.
            log.warning("No dashboard token is set, so the camera stream is limited to this Pi (reach it with an SSH "
                        "tunnel). Set BOB_STREAM_TOKEN, or TOKEN_NAME lines, in .env to make it available on your network.")
            host = "127.0.0.1"
        self._httpd = Server((host, self.cfg.port), Handler)
        threading.Thread(target=self._httpd.serve_forever, name="stream", daemon=True).start()
        auth = " (token required)" if self.policy.configured else " (this Pi only, no password)"
        log.info("Camera stream on %s:%d%s", host, self.cfg.port, auth)
        self._start_https(TlsServer, Handler)

    def _start_https(self, TlsServer, Handler) -> None:
        """The app's secure port, with Bonjour so the app can find Bob. Skipped if there's nowhere to keep the certificate."""
        if not (self.cfg.https and self.base):
            return
        from certs import ensure_cert, server_context
        made = ensure_cert(Path(self.base) / "certs")
        if made is None:
            log.warning("HTTPS (the Bob app) is off: no certificate could be made")
            return
        cert, key, self.fingerprint = made
        robot = self.controller.cfg.radio.name if self.controller else "Bob"
        self.pairing = appapi.Pairing(self.devices, self.fingerprint, robot)
        try:
            TlsServer.context = server_context(cert, key)
            self._httpsd = TlsServer((self.cfg.host, self.cfg.https_port), Handler)
        except (OSError, ssl.SSLError) as e:
            log.warning("HTTPS (the Bob app) is off: %s", e)
            self._httpsd = None
            return
        threading.Thread(target=self._httpsd.serve_forever, name="stream-https", daemon=True).start()
        log.info("Bob app port (HTTPS) on %s:%d, certificate %s...", self.cfg.host, self._httpsd.server_address[1], self.fingerprint[:12])
        if self.cfg.bonjour:
            from bonjour import Bonjour
            self.bonjour = Bonjour(f"{robot} ({socket.gethostname().split('.')[0]})", self._httpsd.server_address[1],
                                   {"v": "1", "fp": self.fingerprint[:16], "name": robot})
            self.bonjour.start()

    def stop(self) -> None:
        if self.bonjour:
            self.bonjour.stop()
        if self._httpsd:
            self._httpsd.shutdown()
            self._httpsd.server_close()
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()   # release the port
