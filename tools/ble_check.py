#!/usr/bin/env python3
"""Check Bob's Bluetooth control from your Mac, without the app. Run it from the project folder, near Bob, with Bob's Wi-Fi still working:

    python3 tools/ble_check.py --host 192.168.1.50 --code ABCD1234EFGH         # first time: pairs a test device called "ble-check"
    python3 tools/ble_check.py --device a1a0a419 --key <64 hex digits>         # later: reuse the key it printed

It scans for Bob's Bluetooth service, says hello, asks for his status, and (only if you add --drive) sends one very gentle forward pulse and then a stop.
It never moves him otherwise. Needs: pip install bleak. Remove the test device afterwards with /devices remove ble-check on Bob.
The message building and signing here is the same code Bob and the app use (blecodec.py).
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import http.client
import json
import secrets
import ssl
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import appapi  # noqa: E402
import blecodec  # noqa: E402


def build(dev: str, key: str, nonce: str, ctr: int, cmd: str, args: str = "") -> str:
    """A signed message line, ready to send: cmd is D, S, T or C (args: "0.30 0.30" for D, the text for C)."""
    if cmd == "D":
        return f"D {dev} {ctr} {args} {blecodec.mac(key, dev, nonce, ctr, 'D ' + args)}"
    if cmd == "C":
        return f"C {dev} {ctr} {blecodec.mac(key, dev, nonce, ctr, 'C ' + args)} {args}"
    return f"{cmd} {dev} {ctr} {blecodec.mac(key, dev, nonce, ctr, cmd)}"


def pair_over_wifi(host: str, code: str) -> tuple[str, str]:
    """Pair a test device with a /pair code, over Wi-Fi, and ask for its Bluetooth key. Returns (device id, key)."""
    host, _, port = host.partition(":")
    port = int(port or 8443)
    ctx = ssl.create_default_context()
    ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    import socket
    with socket.create_connection((host, port), timeout=8) as raw, ctx.wrap_socket(raw) as tls:
        fingerprint = hashlib.sha256(tls.getpeercert(binary_form=True)).hexdigest()

    def post(path, body, token=None):
        c = http.client.HTTPSConnection(host, port, timeout=8, context=ctx)
        h = {"Content-Type": "application/json"}
        if token:
            h["Authorization"] = f"Bearer {token}"
        c.request("POST", path, json.dumps(body).encode(), h)
        r = c.getresponse()
        data = json.loads(r.read() or b"{}")
        c.close()
        if r.status != 200:
            raise SystemExit(f"{path}: {r.status} {data.get('error', data)}")
        return data

    nonce = secrets.token_urlsafe(12)
    paired = post("/api/v1/pair", {"device": "ble-check", "nonce": nonce, "proof": appapi.client_proof(code, nonce, fingerprint)})
    if paired["server_proof"] != appapi.server_proof(code, nonce, fingerprint, paired["token"]):
        raise SystemExit("Bob's answer didn't prove he knows the code: stopping")
    info = post("/api/v1/ble", {}, paired["token"])
    if not info.get("enabled"):
        print("Note: Bob says Bluetooth control is OFF ([ble] enabled = true in his config.local.toml, then restart him).")
    return info["device"], info["key"]


async def run(dev: str, key: str, drive: bool, seconds: float) -> int:
    from bleak import BleakClient, BleakScanner
    print("Looking for Bob's Bluetooth service...")
    found = await BleakScanner.find_device_by_filter(lambda d, ad: blecodec.SERVICE in [u.lower() for u in (ad.service_uuids or [])], timeout=seconds)
    if found is None:
        print("Not found. Is [ble] enabled and Bob restarted? Is Bluetooth on, and are you within a few metres? (/ble on Bob says whether it is running.)")
        return 1
    print(f"Found '{found.name or found.address}'. Connecting...")
    got: list[str] = []
    assembler = blecodec.LineAssembler()

    def on_notify(_, data: bytearray) -> None:
        for line in assembler.feed(bytes(data)):
            got.append(line)
            print(f"  Bob says: {line}")

    async with BleakClient(found) as client:
        await client.start_notify(blecodec.TX, on_notify)

        async def send(text: str) -> None:
            for piece in blecodec.chunks(text):
                await client.write_gatt_char(blecodec.RX, piece, response=False)
                await asyncio.sleep(0.03)

        async def wait_for(prefix: str, t: float = 3.0) -> str | None:
            for _ in range(int(t / 0.05)):
                for line in got:
                    if line.startswith(prefix):
                        got.remove(line)
                        return line
                await asyncio.sleep(0.05)
            return None

        await send(f"H {dev}")
        hello = await wait_for("N ") or await wait_for("ERR", 0.1)
        if not hello or not hello.startswith("N "):
            print(f"Hello failed ({hello or 'no answer'}).")
            return 1
        nonce = hello[2:].strip()
        print("Hello worked: Bob knows this device.")
        ctr = 1
        await send(build(dev, key, nonce, ctr, "T"))
        status = await wait_for("T ")
        print("Status:", status or "no answer")
        if drive:
            input("Wheels lifted? Press Enter to send one gentle forward pulse (0.3 speed, 0.4 s) and then stop...")
            ctr += 1
            await send(build(dev, key, nonce, ctr, "D", "0.30 0.30"))
            await asyncio.sleep(0.5)
            ctr += 1
            await send(build(dev, key, nonce, ctr, "S"))
            print("Sent a pulse and a stop.")
        ok = status is not None
        print("RESULT:", "Bluetooth control works." if ok else "No status came back: something is wrong.")
        return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Check Bob's Bluetooth control without the app")
    ap.add_argument("--host", help="Bob's address on Wi-Fi, for the first run (adds :port if it isn't 8443)")
    ap.add_argument("--code", help="a pairing code from /pair on Bob, for the first run")
    ap.add_argument("--device", help="the device id printed by the first run")
    ap.add_argument("--key", help="the key printed by the first run")
    ap.add_argument("--drive", action="store_true", help="also send one gentle forward pulse and a stop (wheels lifted!)")
    ap.add_argument("--scan-seconds", type=float, default=15.0)
    a = ap.parse_args()
    if a.host and a.code:
        a.device, a.key = pair_over_wifi(a.host, a.code)
        print(f"Paired. To run again without a code: --device {a.device} --key {a.key}")
    if not (a.device and a.key):
        ap.error("give --host and --code (first run), or --device and --key")
    sys.exit(asyncio.run(run(a.device, a.key, a.drive, a.scan_seconds)))


if __name__ == "__main__":
    main()
