from datetime import date, timedelta

from src.auth import SchwabAuth
from src.client import SchwabClient
from src.config import SchwabConfig
from src.models import TokenSet, utcnow


class MemoryStore:
    def __init__(self, tokens):
        self.tokens = tokens

    def load(self):
        return self.tokens

    def save(self, tokens):
        self.tokens = tokens


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.gets = []
        self.posts = []

    def get(self, url, headers=None, params=None, timeout=None):
        self.gets.append(
            {"url": url, "headers": headers, "params": params, "timeout": timeout}
        )
        return self.responses.pop(0)

    def post(self, url, headers=None, data=None, timeout=None):
        self.posts.append(
            {"url": url, "headers": headers, "data": data, "timeout": timeout}
        )
        return FakeResponse(
            {
                "access_token": "fresh",
                "refresh_token": "refresh",
                "expires_in": 1800,
            }
        )


def config():
    return SchwabConfig(
        client_id="client",
        client_secret="secret",
        redirect_uri="https://127.0.0.1/callback",
    )


def token():
    return TokenSet(
        access_token="access",
        refresh_token="refresh",
        expires_at=utcnow() + timedelta(minutes=20),
    )


def client_with_responses(responses):
    store = MemoryStore(token())
    session = FakeSession(responses)
    auth = SchwabAuth(config(), store, session=session)
    return SchwabClient(config(), auth, session=session), session


def test_list_accounts_uses_account_numbers_endpoint():
    client, session = client_with_responses(
        [FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}])]
    )

    accounts = client.list_accounts()

    assert accounts[0].account_number == "1234"
    assert accounts[0].hash_value == "hash-1"
    assert session.gets[0]["url"].endswith("/trader/v1/accounts/accountNumbers")


def test_get_positions_fetches_each_account_with_positions_field():
    client, session = client_with_responses(
        [
            FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}]),
            FakeResponse(
                {
                    "securitiesAccount": {
                        "accountNumber": "1234",
                        "type": "MARGIN",
                        "positions": [
                            {
                                "longQuantity": 2,
                                "averagePrice": 100,
                                "marketValue": 210,
                                "instrument": {
                                    "symbol": "AAPL",
                                    "assetType": "EQUITY",
                                },
                            }
                        ],
                    }
                }
            ),
        ]
    )

    accounts = client.get_positions()

    assert accounts[0].securities_account.positions[0].instrument.symbol == "AAPL"
    assert session.gets[1]["url"].endswith("/trader/v1/accounts/hash-1")
    assert session.gets[1]["params"] == {"fields": "positions"}


def test_get_positions_and_balances_fetches_both_fields():
    client, session = client_with_responses(
        [
            FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}]),
            FakeResponse(
                {
                    "securitiesAccount": {
                        "accountNumber": "1234",
                        "type": "MARGIN",
                        "currentBalances": {
                            "cashBalance": 1000,
                            "optionBuyingPower": 5000,
                            "liquidationValue": 10000,
                        },
                    }
                }
            ),
        ]
    )

    accounts = client.get_positions_and_balances()

    assert accounts[0].securities_account.current_balances.cash_balance == 1000
    assert session.gets[1]["params"] == {"fields": "positions"}


def test_get_retries_once_after_unauthorized_and_refreshes_token():
    client, session = client_with_responses(
        [
            FakeResponse({}, status_code=401),
            FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}]),
        ]
    )

    accounts = client.list_accounts()

    assert accounts[0].hash_value == "hash-1"
    assert len(session.posts) == 1
    assert session.gets[1]["headers"]["Authorization"] == "Bearer fresh"


def test_get_open_orders_queries_open_statuses_for_each_account():
    client, session = client_with_responses(
        [
            FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}]),
            FakeResponse([{"orderId": 1, "status": "WORKING"}]),
            FakeResponse([]),
            FakeResponse([]),
        ]
    )

    orders = client.get_open_orders()

    assert orders[0].order_id == 1
    statuses = [request["params"]["status"] for request in session.gets[1:]]
    assert statuses == ["WORKING", "QUEUED", "AWAITING_PARENT_ORDER"]
    assert session.gets[1]["params"]["maxResults"] == 3000


def test_get_transactions_queries_trade_history_in_chunks():
    client, session = client_with_responses(
        [
            FakeResponse([{"accountNumber": "1234", "hashValue": "hash-1"}]),
            FakeResponse([{"activityId": 1, "netAmount": 150, "type": "TRADE"}]),
            FakeResponse([{"activityId": 2, "netAmount": -40, "type": "TRADE"}]),
        ]
    )

    transactions = client.get_transactions(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 4, 1),
    )

    assert [transaction.activity_id for transaction in transactions] == [1, 2]
    assert session.gets[1]["url"].endswith("/trader/v1/accounts/hash-1/transactions")
    assert session.gets[1]["params"]["types"] == "TRADE"
    assert session.gets[1]["params"]["startDate"] == "2026-01-01T00:00:00Z"
    assert session.gets[1]["params"]["endDate"] == "2026-03-01T23:59:59.999Z"
    assert session.gets[2]["params"]["startDate"] == "2026-03-02T00:00:00Z"


def test_get_option_chain_uses_marketdata_chains_endpoint():
    client, session = client_with_responses(
        [
            FakeResponse(
                {
                    "symbol": "AAPL",
                    "underlyingPrice": 100,
                    "callExpDateMap": {},
                    "putExpDateMap": {},
                }
            )
        ]
    )

    chain = client.get_option_chain(
        "aapl",
        from_date=date(2026, 4, 21),
        to_date=date(2026, 6, 4),
    )

    assert chain.symbol == "AAPL"
    assert session.gets[0]["url"].endswith("/marketdata/v1/chains")
    assert session.gets[0]["params"] == {
        "symbol": "AAPL",
        "contractType": "ALL",
        "includeUnderlyingQuote": "true",
        "fromDate": "2026-04-21",
        "toDate": "2026-06-04",
    }
