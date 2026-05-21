from datetime import timedelta

from src.models import TokenSet, utcnow
from src.token_store import (
    EncryptedFileTokenStore,
    KeyringTokenStore,
    build_token_store,
)


def test_encrypted_file_token_store_round_trips_tokens(tmp_path):
    path = tmp_path / "tokens.enc"
    store = EncryptedFileTokenStore(path, passphrase="not-for-production")
    tokens = TokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=utcnow() + timedelta(minutes=30),
    )

    store.save(tokens)
    loaded = store.load()

    assert loaded.access_token == "access"
    assert loaded.refresh_token == "refresh"
    assert "access" not in path.read_text(encoding="utf-8")


def test_build_token_store_can_force_encrypted_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHWAB_TOKEN_STORE", "file")
    monkeypatch.setenv("SCHWAB_TOKEN_PASSPHRASE", "not-for-production")

    store = build_token_store("service", tmp_path / "tokens.enc")

    assert isinstance(store, EncryptedFileTokenStore)


def test_build_token_store_can_force_keyring(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHWAB_TOKEN_STORE", "keyring")

    store = build_token_store("service", tmp_path / "tokens.enc")

    assert isinstance(store, KeyringTokenStore)
