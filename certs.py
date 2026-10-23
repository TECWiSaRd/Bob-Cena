"""Bob's own HTTPS certificate, made the first time it is needed and kept in certs/ (never committed).

It is self-signed, so a browser warns about it. The Bob app doesn't rely on that trust: when it pairs with Bob it learns
the certificate's fingerprint and from then on accepts only that exact certificate (pinning). Deleting the certs/ folder
makes a new certificate and every paired phone and computer has to pair again.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import ssl
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("bob.certs")

VALID_DAYS = 3650


def fingerprint(cert_path: Path) -> str:
    """SHA-256 of the certificate (in DER form), lower-case hex. This is what a paired app pins."""
    der = ssl.PEM_cert_to_DER_cert(Path(cert_path).read_text())
    return hashlib.sha256(der).hexdigest()


def ensure_cert(folder: Path, hostname: str | None = None, run=subprocess.run) -> tuple[Path, Path, str] | None:
    """(certificate, key, fingerprint), making them if they don't exist yet. None if that isn't possible here."""
    folder = Path(folder)
    cert, key = folder / "bob-cert.pem", folder / "bob-key.pem"
    if cert.exists() and key.exists():
        try:
            return cert, key, fingerprint(cert)
        except (OSError, ssl.SSLError, ValueError):
            log.warning("The saved HTTPS certificate is unreadable; making a new one")
    host = (hostname or socket.gethostname() or "bob").split(".")[0]
    try:
        folder.mkdir(parents=True, exist_ok=True)
        os.chmod(folder, 0o700)
        names = f"DNS:{host}.local,DNS:{host},DNS:localhost,IP:127.0.0.1"
        with tempfile.TemporaryDirectory(dir=folder) as tmp:
            tmp_cert, tmp_key = Path(tmp) / "c.pem", Path(tmp) / "k.pem"
            done = run(["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes",
                        "-days", str(VALID_DAYS), "-subj", f"/CN={host}", "-addext", f"subjectAltName={names}",
                        "-keyout", str(tmp_key), "-out", str(tmp_cert)], capture_output=True, text=True, timeout=60)
            if done.returncode != 0:
                log.warning("Couldn't make an HTTPS certificate: %s", (done.stderr or "openssl failed").strip().splitlines()[-1])
                return None
            os.chmod(tmp_key, 0o600)
            os.replace(tmp_key, key)                    # the key first: a certificate never exists without its key
            os.replace(tmp_cert, cert)
        return cert, key, fingerprint(cert)
    except FileNotFoundError:
        log.warning("HTTPS is off: openssl isn't installed (sudo apt-get install openssl)")
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("Couldn't make an HTTPS certificate: %s", e)
    return None


def server_context(cert: Path, key: Path) -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(str(cert), str(key))
    return ctx
