from __future__ import annotations

import ipaddress
import ssl
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import parse_qs, urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


@dataclass(frozen=True)
class CallbackResult:
    code: str
    state: Optional[str] = None


def wait_for_oauth_callback(redirect_uri: str, timeout_seconds: int = 180) -> CallbackResult:
    parsed = urlparse(redirect_uri)
    if parsed.scheme != "https":
        raise RuntimeError("Local callback listener requires an https redirect URI.")
    if not parsed.hostname:
        raise RuntimeError("Redirect URI must include a hostname.")

    host = parsed.hostname
    port = parsed.port or 443
    expected_path = parsed.path or "/"
    result: dict[str, CallbackResult] = {}
    error: dict[str, str] = {}
    ready = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlparse(self.path)
            if request.path != expected_path:
                self._send(404, "Unexpected callback path.")
                return

            params = parse_qs(request.query)
            if params.get("error"):
                error["message"] = params["error"][0]
                self._send(400, "Schwab returned an OAuth error. You can close this tab.")
                ready.set()
                return

            codes = params.get("code")
            if not codes:
                self._send(400, "No authorization code was provided.")
                ready.set()
                return

            states = params.get("state")
            result["callback"] = CallbackResult(
                code=codes[0],
                state=states[0] if states else None,
            )
            self._send(200, "Schwab authorization complete. You can close this tab.")
            ready.set()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _send(self, status: int, body: str) -> None:
            payload = (
                "<!doctype html><html><body>"
                f"<h1>{body}</h1>"
                "</body></html>"
            ).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = HTTPServer((host, port), Handler)
    with tempfile.TemporaryDirectory() as directory:
        cert_path, key_path = create_self_signed_cert(host, Path(directory))
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert_path), str(key_path))
        server.socket = context.wrap_socket(server.socket, server_side=True)

        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            if not ready.wait(timeout_seconds):
                raise TimeoutError("Timed out waiting for Schwab OAuth callback.")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    if error:
        raise RuntimeError(f"Schwab OAuth callback failed: {error['message']}")
    if "callback" not in result:
        raise RuntimeError("No Schwab OAuth callback was captured.")
    return result["callback"]


def create_self_signed_cert(hostname: str, directory: Path) -> Tuple[Path, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Wheel Desk Local OAuth"),
            x509.NameAttribute(NameOID.COMMON_NAME, hostname),
        ]
    )
    san = _subject_alt_name(hostname)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow() - timedelta(minutes=1))
        .not_valid_after(datetime.utcnow() + timedelta(days=1))
        .add_extension(san, critical=False)
        .sign(key, hashes.SHA256())
    )

    cert_path = directory / "localhost.crt"
    key_path = directory / "localhost.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _subject_alt_name(hostname: str) -> x509.SubjectAlternativeName:
    try:
        return x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(hostname))])
    except ValueError:
        return x509.SubjectAlternativeName([x509.DNSName(hostname)])
