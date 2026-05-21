from datetime import date
import json

from src import app
from src.models import Account, AccountNumber, OptionChain, Transaction


class FakeClient:
    def list_accounts(self):
        return [AccountNumber(accountNumber="1234", hashValue="hash-1")]

    def get_positions(self):
        return [
            Account.model_validate(
                {
                    "securitiesAccount": {
                        "accountNumber": "1234",
                        "positions": [
                            {
                                "longQuantity": 1,
                                "marketValue": 100,
                                "instrument": {"symbol": "MSFT", "assetType": "EQUITY"},
                            }
                        ],
                    }
                }
            )
        ]

    def get_positions_and_balances(self):
        return self.get_positions()

    def get_transactions(self, start_date, end_date):
        return []

    def get_option_chain(self, symbol, from_date, to_date):
        return OptionChain.model_validate(
            {
                "symbol": symbol.upper(),
                "underlyingPrice": 100,
                "callExpDateMap": {},
                "putExpDateMap": {},
            }
        )


def test_positions_command_prints_positions(monkeypatch, capsys):
    monkeypatch.setattr(app, "build_client", lambda: FakeClient())

    exit_code = app.main(["positions"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"symbol": "MSFT"' in output
    assert '"account": "1234"' in output


def test_wheel_summary_command_prints_attention_lists(monkeypatch, capsys):
    class WheelClient:
        def get_positions_and_balances(self):
            return [
                Account.model_validate(
                    {
                        "securitiesAccount": {
                            "accountNumber": "1234",
                            "positions": [
                                {
                                    "shortQuantity": 1,
                                    "averagePrice": 2.0,
                                    "marketValue": -35.0,
                                    "instrument": {
                                        "symbol": "AAPL  260424P00180000",
                                        "assetType": "OPTION",
                                        "putCall": "PUT",
                                        "underlyingSymbol": "AAPL",
                                        "expirationDate": "2026-04-24",
                                        "strikePrice": 180,
                                    },
                                }
                            ],
                            "currentBalances": {
                                "cashBalance": 1000,
                                "optionBuyingPower": 5000,
                            },
                        }
                    }
                )
            ]

        def get_transactions(self, start_date, end_date):
            return [
                Transaction.from_payload(
                    {
                        "transactionDate": "2026-04-01T16:00:00Z",
                        "netAmount": 150.0,
                        "transactionItem": {
                            "instrument": {
                                "symbol": "AAPL  260424P00180000",
                                "assetType": "OPTION",
                            }
                        },
                    }
                )
            ]

    monkeypatch.setattr(app, "build_client", lambda: WheelClient())

    exit_code = app.main(["wheel-summary", "--profit-threshold", "0.8"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"profit_targets"' in output
    assert '"profit_loss"' in output
    assert '"balances"' in output
    assert '"underlying": "AAPL"' in output


def test_wheel_summary_command_defaults_to_five_expiry_days(monkeypatch):
    captured = {}

    class WheelClient:
        def get_positions_and_balances(self):
            return []

        def get_transactions(self, start_date, end_date):
            return []

    def fake_summary(accounts, transactions, as_of, profit_threshold, expiry_days):
        captured["expiry_days"] = expiry_days

        class Summary:
            def to_dict(self):
                return {}

        return Summary()

    monkeypatch.setattr(app, "build_client", lambda: WheelClient())
    monkeypatch.setattr(app, "build_wheel_summary", fake_summary)

    exit_code = app.main(["wheel-summary"])

    assert exit_code == 0
    assert captured["expiry_days"] == 5


def test_option_chain_command_prints_filtered_chain(monkeypatch, capsys):
    class FakeDate:
        @classmethod
        def today(cls):
            return date(2026, 4, 21)

    class ChainClient:
        def get_option_chain(self, symbol, from_date, to_date):
            assert from_date == date(2026, 4, 21)
            assert to_date == date(2026, 6, 4)
            return OptionChain.model_validate(
                {
                    "symbol": symbol.upper(),
                    "underlyingPrice": 100,
                    "callExpDateMap": {
                        "2026-05-01:10": {
                            "100.0": [
                                {
                                    "putCall": "CALL",
                                    "symbol": "AAPL  260501C00100000",
                                    "strikePrice": 100,
                                    "expirationDate": "2026-05-01",
                                }
                            ]
                        }
                    },
                    "putExpDateMap": {},
                }
            )

    monkeypatch.setattr(app, "build_client", lambda: ChainClient())
    monkeypatch.setattr(app, "date", FakeDate)

    exit_code = app.main(["option-chain", "aapl"])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"underlying_price": 100.0' in output
    assert '"symbol": "AAPL  260501C00100000"' in output


def test_wheel_agent_command_prints_recommendations(monkeypatch, capsys, tmp_path):
    class AgentClient:
        def get_positions_and_balances(self):
            return [
                Account.model_validate(
                    {
                        "securitiesAccount": {
                            "accountNumber": "1234",
                            "currentBalances": {
                                "cashBalance": 50000,
                                "liquidationValue": 100000,
                            },
                            "positions": [
                                {
                                    "longQuantity": 100,
                                    "averagePrice": 80,
                                    "instrument": {
                                        "symbol": "AAPL",
                                        "assetType": "EQUITY",
                                    },
                                }
                            ],
                        }
                    }
                )
            ]

        def get_transactions(self, start_date, end_date):
            return []

        def get_option_chain(self, symbol, from_date, to_date):
            return OptionChain.model_validate(
                {
                    "symbol": symbol.upper(),
                    "underlyingPrice": 100,
                    "callExpDateMap": {
                        "2026-06-18:30": {
                            "110.0": [
                                {
                                    "putCall": "CALL",
                                    "symbol": "AAPL  260618C00110000",
                                    "strikePrice": 110,
                                    "expirationDate": "2026-06-18",
                                    "bid": 3.5,
                                    "delta": 0.25,
                                }
                            ]
                        }
                    },
                    "putExpDateMap": {},
                }
            )

    symbol_file = tmp_path / "symbols.txt"
    symbol_file.write_text("AAPL\n", encoding="utf-8")
    monkeypatch.setattr(app, "build_client", lambda: AgentClient())

    exit_code = app.main(["wheel-agent", "--symbols-file", str(symbol_file)])

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"recommendations"' in output
    assert '"SELL_COVERED_CALL"' in output


def test_wheel_agent_command_returns_json_when_schwab_lookup_fails(monkeypatch, capsys):
    class FailingClient:
        def get_positions_and_balances(self):
            raise RuntimeError("DNS failure for api.schwabapi.com")

    monkeypatch.setattr(app, "build_client", lambda: FailingClient())

    exit_code = app.main(["wheel-agent", "--symbols", "AAPL"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["blocked_stage"] == "account_or_transaction_lookup"
    assert payload["recommendations"] == {
        "rolls": [],
        "covered_calls": [],
        "cash_secured_puts": [],
        "by_account": [],
    }
    assert "DNS failure" in payload["error"]


def test_extract_authorization_code_accepts_full_callback_url():
    code = app.extract_authorization_code(
        "https://127.0.0.1:8083/auth-redirect?code=abc123&state=xyz"
    )

    assert code == "abc123"


def test_auth_login_can_open_browser(monkeypatch, capsys):
    opened = []
    exchanged = []

    class FakeAuth:
        class Config:
            redirect_uri = "https://127.0.0.1:8083/auth-redirect"

        config = Config()

        def authorization_url(self, state=None):
            return f"https://schwab.example/authorize?state={state}"

        def exchange_code(self, code):
            exchanged.append(code)

    class FakeCallback:
        code = "code-123"

    monkeypatch.setattr(app, "build_auth", lambda: FakeAuth())
    monkeypatch.setattr(app.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(
        app,
        "wait_for_oauth_callback",
        lambda redirect_uri, timeout_seconds: FakeCallback(),
    )

    exit_code = app.main(["auth-login", "--open", "--state", "state-123"])

    assert exit_code == 0
    assert opened == ["https://schwab.example/authorize?state=state-123"]
    assert exchanged == ["code-123"]
    assert "Schwab tokens stored." in capsys.readouterr().out


def test_auth_export_file_copies_keyring_tokens_to_encrypted_file(
    monkeypatch, tmp_path, capsys
):
    class FakeConfig:
        keyring_service = "service"
        token_path = tmp_path / "tokens.enc"

    class FakeKeyringStore:
        def __init__(self, service):
            self.service = service

        def load(self):
            return Transaction.from_payload(
                {
                    "transactionDate": "2026-04-01",
                    "netAmount": 1,
                }
            )

    saved = []

    class FakeFileStore:
        def __init__(self, path, passphrase):
            self.path = path
            self.passphrase = passphrase

        def save(self, tokens):
            saved.append((self.path, self.passphrase, tokens.net_amount))

    monkeypatch.setenv("SCHWAB_TOKEN_PASSPHRASE", "secret")
    monkeypatch.setattr(app.SchwabConfig, "from_env", lambda: FakeConfig())
    monkeypatch.setattr(app, "KeyringTokenStore", FakeKeyringStore)
    monkeypatch.setattr(app, "EncryptedFileTokenStore", FakeFileStore)

    exit_code = app.main(["auth-export-file"])

    assert exit_code == 0
    assert saved == [(tmp_path / "tokens.enc", "secret", 1)]
    assert "Schwab tokens exported" in capsys.readouterr().out


def test_auth_check_reports_sanitized_config(monkeypatch, tmp_path, capsys):
    class FakeConfig:
        client_id = "abc123456"
        token_path = tmp_path / "tokens.enc"
        keyring_service = "service"
        auth_base_url = "https://api.schwabapi.com/v1/oauth"
        trader_base_url = "https://api.schwabapi.com/trader/v1"
        marketdata_base_url = "https://api.schwabapi.com/marketdata/v1"
        redirect_uri = "https://127.0.0.1:8083/auth-redirect"

    class FakeStore:
        def load(self):
            return object()

    monkeypatch.setenv("SCHWAB_TOKEN_STORE", "file")
    monkeypatch.setattr(app.SchwabConfig, "from_env", lambda: FakeConfig())
    monkeypatch.setattr(app, "build_token_store", lambda service, path: FakeStore())

    exit_code = app.main(["auth-check"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "ok"
    assert payload["client_id_suffix"] == "123456"
    assert "secret" not in payload
