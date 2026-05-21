from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


DEFAULT_AUTH_BASE_URL = "https://api.schwabapi.com/v1/oauth"
DEFAULT_TRADER_BASE_URL = "https://api.schwabapi.com/trader/v1"
DEFAULT_MARKETDATA_BASE_URL = "https://api.schwabapi.com/marketdata/v1"
DEFAULT_TOKEN_PATH = Path.home() / ".schwab-assistant" / "tokens.enc"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class SchwabConfig:
    client_id: str
    client_secret: str
    redirect_uri: str
    auth_base_url: str = DEFAULT_AUTH_BASE_URL
    trader_base_url: str = DEFAULT_TRADER_BASE_URL
    marketdata_base_url: str = DEFAULT_MARKETDATA_BASE_URL
    token_path: Path = DEFAULT_TOKEN_PATH
    keyring_service: str = "wheel-desk-schwab"

    @classmethod
    def from_env(cls) -> "SchwabConfig":
        load_dotenv()
        missing = [
            name
            for name in (
                "SCHWAB_CLIENT_ID",
                "SCHWAB_CLIENT_SECRET",
                "SCHWAB_REDIRECT_URI",
            )
            if not os.getenv(name)
        ]
        if missing:
            joined = ", ".join(missing)
            raise RuntimeError(f"Missing required environment variable(s): {joined}")

        token_path = Path(os.getenv("SCHWAB_TOKEN_PATH", str(DEFAULT_TOKEN_PATH)))
        return cls(
            client_id=os.environ["SCHWAB_CLIENT_ID"],
            client_secret=os.environ["SCHWAB_CLIENT_SECRET"],
            redirect_uri=os.environ["SCHWAB_REDIRECT_URI"],
            auth_base_url=os.getenv("SCHWAB_AUTH_BASE_URL", DEFAULT_AUTH_BASE_URL),
            trader_base_url=os.getenv(
                "SCHWAB_TRADER_BASE_URL", DEFAULT_TRADER_BASE_URL
            ),
            marketdata_base_url=os.getenv(
                "SCHWAB_MARKETDATA_BASE_URL", DEFAULT_MARKETDATA_BASE_URL
            ),
            token_path=token_path,
            keyring_service=os.getenv("SCHWAB_KEYRING_SERVICE", "wheel-desk-schwab"),
        )


def load_dotenv(path: Optional[Path] = None) -> None:
    for candidate in dotenv_candidate_paths(path):
        if not candidate.exists():
            continue
        for key, value in parse_dotenv(candidate).items():
            os.environ.setdefault(key, value)


def dotenv_candidate_paths(path: Optional[Path] = None) -> List[Path]:
    if path is not None:
        return [path]

    candidates: List[Path] = []
    env_file = os.getenv("SCHWAB_ENV_FILE")
    if env_file:
        candidates.append(Path(env_file))

    candidates.append(Path.cwd() / ".env")
    candidates.append(PROJECT_ROOT / ".env")

    unique: List[Path] = []
    seen = set()
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def parse_dotenv(path: Path) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values
