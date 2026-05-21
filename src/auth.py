from __future__ import annotations

import base64
from typing import Any, Dict, Optional
from urllib.parse import urlencode

import requests

from .config import SchwabConfig
from .models import TokenSet
from .token_store import TokenStore


class SchwabAuth:
    def __init__(
        self,
        config: SchwabConfig,
        token_store: TokenStore,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.token_store = token_store
        self.session = session or requests.Session()

    def authorization_url(self, state: Optional[str] = None) -> str:
        query = {
            "response_type": "code",
            "client_id": self.config.client_id,
            "redirect_uri": self.config.redirect_uri,
        }
        if state:
            query["state"] = state
        return f"{self.config.auth_base_url}/authorize?{urlencode(query)}"

    def exchange_code(self, code: str) -> TokenSet:
        tokens = self._post_token(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.config.redirect_uri,
            }
        )
        self.token_store.save(tokens)
        return tokens

    def refresh(self, refresh_token: str) -> TokenSet:
        tokens = self._post_token(
            {"grant_type": "refresh_token", "refresh_token": refresh_token}
        )
        self.token_store.save(tokens)
        return tokens

    def valid_tokens(self) -> TokenSet:
        tokens = self.token_store.load()
        if tokens is None:
            raise RuntimeError("No Schwab tokens stored. Run `python -m src.app auth-url`.")
        if tokens.access_token_expired():
            return self.refresh(tokens.refresh_token)
        return tokens

    def _post_token(self, data: Dict[str, Any]) -> TokenSet:
        response = self.session.post(
            f"{self.config.auth_base_url}/token",
            headers={
                "Authorization": f"Basic {self._basic_credentials()}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data=data,
            timeout=30,
        )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            message = response.text.strip()
            if not message:
                message = response.reason
            raise RuntimeError(
                f"Schwab token request failed ({response.status_code}): {message}"
            ) from exc
        return TokenSet.from_oauth_response(response.json())

    def _basic_credentials(self) -> str:
        raw = f"{self.config.client_id}:{self.config.client_secret}".encode("utf-8")
        return base64.b64encode(raw).decode("ascii")
