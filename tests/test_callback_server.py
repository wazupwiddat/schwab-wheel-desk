import ssl
import threading
from urllib.request import urlopen

from src.callback_server import create_self_signed_cert, wait_for_oauth_callback


def test_create_self_signed_cert_writes_cert_and_key(tmp_path):
    cert_path, key_path = create_self_signed_cert("127.0.0.1", tmp_path)

    assert "BEGIN CERTIFICATE" in cert_path.read_text(encoding="utf-8")
    assert "BEGIN RSA PRIVATE KEY" in key_path.read_text(encoding="utf-8")


def test_wait_for_oauth_callback_captures_code():
    redirect_uri = "https://127.0.0.1:18083/auth-redirect"
    captured = {}

    def run_server():
        captured["result"] = wait_for_oauth_callback(redirect_uri, timeout_seconds=5)

    thread = threading.Thread(target=run_server)
    thread.start()

    context = ssl._create_unverified_context()
    with urlopen(
        "https://127.0.0.1:18083/auth-redirect?code=abc123&state=xyz",
        context=context,
        timeout=5,
    ) as response:
        assert response.status == 200

    thread.join(timeout=5)

    assert captured["result"].code == "abc123"
    assert captured["result"].state == "xyz"
