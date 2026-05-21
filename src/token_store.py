from __future__ import annotations

import base64
import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

import keyring
from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from keyring.errors import KeyringError

from .models import TokenSet


class TokenStore(ABC):
    @abstractmethod
    def load(self) -> Optional[TokenSet]:
        raise NotImplementedError

    @abstractmethod
    def save(self, tokens: TokenSet) -> None:
        raise NotImplementedError


class KeyringTokenStore(TokenStore):
    def __init__(self, service: str, username: str = "tokens") -> None:
        self.service = service
        self.username = username

    def load(self) -> Optional[TokenSet]:
        try:
            value = keyring.get_password(self.service, self.username)
        except KeyringError:
            return None
        if not value:
            return None
        return TokenSet.model_validate_json(value)

    def save(self, tokens: TokenSet) -> None:
        keyring.set_password(
            self.service, self.username, tokens.model_dump_json()
        )


class EncryptedFileTokenStore(TokenStore):
    def __init__(self, path: Path, passphrase: str) -> None:
        self.path = path
        self.passphrase = passphrase

    def load(self) -> Optional[TokenSet]:
        if not self.path.exists():
            return None
        envelope = json.loads(self.path.read_text(encoding="utf-8"))
        fernet = self._fernet(bytes.fromhex(envelope["salt"]))
        try:
            decrypted = fernet.decrypt(envelope["token"].encode("utf-8"))
        except InvalidToken as exc:
            raise RuntimeError("Unable to decrypt stored Schwab tokens") from exc
        return TokenSet.model_validate_json(decrypted)

    def save(self, tokens: TokenSet) -> None:
        salt = os.urandom(16)
        fernet = self._fernet(salt)
        encrypted = fernet.encrypt(tokens.model_dump_json().encode("utf-8"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps({"salt": salt.hex(), "token": encrypted.decode("utf-8")}),
            encoding="utf-8",
        )
        self.path.chmod(0o600)

    def _fernet(self, salt: bytes) -> Fernet:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=390000,
        )
        key = base64.urlsafe_b64encode(kdf.derive(self.passphrase.encode("utf-8")))
        return Fernet(key)


def build_token_store(service: str, token_path: Path) -> TokenStore:
    preferred_store = os.getenv("SCHWAB_TOKEN_STORE", "auto").lower()
    passphrase = os.getenv("SCHWAB_TOKEN_PASSPHRASE")

    if preferred_store == "file":
        if not passphrase:
            raise RuntimeError(
                "SCHWAB_TOKEN_STORE=file requires SCHWAB_TOKEN_PASSPHRASE."
            )
        return EncryptedFileTokenStore(token_path, passphrase)

    if preferred_store == "keyring":
        return KeyringTokenStore(service=service)

    try:
        backend = keyring.get_keyring()
        if backend.priority > 0:
            return KeyringTokenStore(service=service)
    except KeyringError:
        pass

    if passphrase:
        return EncryptedFileTokenStore(token_path, passphrase)

    raise RuntimeError(
        "No usable keyring backend found. Set SCHWAB_TOKEN_PASSPHRASE to use "
        "encrypted local token storage."
    )
