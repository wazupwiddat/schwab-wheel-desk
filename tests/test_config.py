import os

from src.config import SchwabConfig, dotenv_candidate_paths, parse_dotenv


def test_parse_dotenv_handles_quotes_and_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        """
        # local Schwab settings
        SCHWAB_CLIENT_ID="client-id"
        SCHWAB_CLIENT_SECRET='secret'
        SCHWAB_REDIRECT_URI=https://127.0.0.1:8083/auth-redirect
        """,
        encoding="utf-8",
    )

    values = parse_dotenv(path)

    assert values["SCHWAB_CLIENT_ID"] == "client-id"
    assert values["SCHWAB_CLIENT_SECRET"] == "secret"
    assert values["SCHWAB_REDIRECT_URI"] == "https://127.0.0.1:8083/auth-redirect"


def test_config_loads_dotenv_without_overriding_existing_env(tmp_path, monkeypatch):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "\n".join(
            [
                "SCHWAB_CLIENT_ID=from-file",
                "SCHWAB_CLIENT_SECRET=from-file",
                "SCHWAB_REDIRECT_URI=https://127.0.0.1:8083/auth-redirect",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCHWAB_CLIENT_ID", "from-env")
    monkeypatch.delenv("SCHWAB_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("SCHWAB_REDIRECT_URI", raising=False)

    config = SchwabConfig.from_env()

    assert config.client_id == "from-env"
    assert config.client_secret == "from-file"
    assert config.redirect_uri == "https://127.0.0.1:8083/auth-redirect"


def test_dotenv_candidate_paths_prefers_explicit_env_file(tmp_path, monkeypatch):
    env_file = tmp_path / "custom.env"
    monkeypatch.setenv("SCHWAB_ENV_FILE", str(env_file))

    paths = dotenv_candidate_paths()

    assert paths[0] == env_file.resolve()
