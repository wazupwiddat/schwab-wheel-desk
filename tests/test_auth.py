from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from src.auth import SchwabAuth
from src.config import SchwabConfig
from src.models import TokenSet, utcnow


class MemoryStore:
    def __init__(self, tokens=None):
        self.tokens = tokens

    def load(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code
        self.text = ""
        self.reason = "OK"

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError("http error")


class FakeSession:
    def __init__(self):
        self.posts = []

    def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append(
            {"url": url, "headers": headers, "data": data, "timeout": timeout}
        )
        return FakeResponse(
            {
                "access_token": "access-new",
                "refresh_token": "refresh-new",
                "token_type": "Bearer",
                "expires_in": 1800,
            }
        )


def config():
    return SchwabConfig(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://127.0.0.1/callback",
    )


def test_authorization_url_contains_required_oauth_params():
    auth = SchwabAuth(config(), MemoryStore())

    parsed = urlparse(auth.authorization_url(state="abc"))
    query = parse_qs(parsed.query)

    assert parsed.path == "/v1/oauth/authorize"
    assert query["response_type"] == ["code"]
    assert query["client_id"] == ["client"]
    assert query["redirect_uri"] == ["https://127.0.0.1/callback"]
    assert query["state"] == ["abc"]


def test_exchange_code_posts_form_and_saves_tokens():
    store = MemoryStore()
    session = FakeSession()
    auth = SchwabAuth(config(), store, session=session)

    tokens = auth.exchange_code("code-123")

    assert tokens.access_token == "access-new"
    assert store.tokens.access_token == "access-new"
    assert session.posts[0]["data"] == {
        "grant_type": "authorization_code",
        "code": "code-123",
        "redirect_uri": "https://127.0.0.1/callback",
    }
    assert session.posts[0]["headers"]["Authorization"].startswith("Basic ")


def test_valid_tokens_refreshes_expired_access_token():
    expired = TokenSet(
        access_token="old",
        refresh_token="refresh-old",
        expires_at=utcnow() - timedelta(minutes=1),
    )
    store = MemoryStore(expired)
    session = FakeSession()
    auth = SchwabAuth(config(), store, session=session)

    tokens = auth.valid_tokens()

    assert tokens.access_token == "access-new"
    assert session.posts[0]["data"] == {
        "grant_type": "refresh_token",
        "refresh_token": "refresh-old",
    }
