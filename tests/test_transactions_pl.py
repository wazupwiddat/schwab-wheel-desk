from datetime import date

from src.models import Transaction
from src.wheel_summary import build_option_profit_loss


def transaction(payload):
    return Transaction.from_payload(payload)


def option_trade(transaction_date, net_amount, symbol="AAPL  260424P00180000"):
    return transaction(
        {
            "activityId": str(net_amount),
            "transactionDate": transaction_date,
            "type": "TRADE",
            "netAmount": net_amount,
            "transactionItem": {
                "instruction": "SELL_TO_OPEN",
                "instrument": {
                    "symbol": symbol,
                    "assetType": "OPTION",
                    "underlyingSymbol": "AAPL",
                },
            },
        }
    )


def test_build_option_profit_loss_sums_month_and_year_to_date_net_amounts():
    transactions = [
        option_trade("2026-01-15T15:30:00Z", 200.0),
        option_trade("2026-04-01T16:00:00Z", 150.0),
        option_trade("2026-04-10T16:00:00Z", -35.0),
        transaction(
            {
                "transactionDate": "2026-04-12T16:00:00Z",
                "type": "TRADE",
                "netAmount": 500.0,
                "transactionItem": {
                    "instrument": {"symbol": "AAPL", "assetType": "EQUITY"}
                },
            }
        ),
        option_trade("2025-12-30T16:00:00Z", 1000.0),
    ]

    profit_loss = build_option_profit_loss(transactions, as_of=date(2026, 4, 18))

    assert profit_loss["month_to_date"] == 115.0
    assert profit_loss["year_to_date"] == 315.0
    assert profit_loss["month_to_date_transaction_count"] == 2
    assert profit_loss["year_to_date_transaction_count"] == 3


def test_build_option_profit_loss_accepts_raw_transaction_items_plural():
    trade = Transaction.from_payload(
        {
            "transactionDate": "2026-04-10",
            "netAmount": 42.0,
            "transactionItems": [
                {
                    "instrument": {
                        "symbol": "MSFT  260424C00400000",
                        "assetType": "OPTION",
                    }
                }
            ],
        }
    )

    profit_loss = build_option_profit_loss([trade], as_of=date(2026, 4, 18))

    assert profit_loss["month_to_date"] == 42.0
    assert profit_loss["year_to_date"] == 42.0


def test_build_option_profit_loss_accepts_schwab_transfer_items_and_time():
    trade = Transaction.from_payload(
        {
            "time": "2026-04-11T15:30:00+0000",
            "netAmount": 78.5,
            "transferItems": [
                {
                    "amount": 78.5,
                    "instrument": {
                        "symbol": "CURRENCY_USD",
                        "assetType": "CURRENCY",
                    },
                },
                {
                    "amount": -1,
                    "positionEffect": "CLOSING",
                    "instrument": {
                        "symbol": "AAPL  260424P00180000",
                        "assetType": "OPTION",
                    },
                },
            ],
        }
    )

    profit_loss = build_option_profit_loss([trade], as_of=date(2026, 4, 18))

    assert profit_loss["month_to_date"] == 78.5
    assert profit_loss["year_to_date"] == 78.5
