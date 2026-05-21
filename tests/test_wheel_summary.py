from datetime import date

from src.models import Account
from src.wheel_summary import (
    build_account_balances,
    build_wheel_summary,
    parse_expiration_date,
)


def account_with_positions(positions):
    return Account.model_validate(
        {
            "securitiesAccount": {
                "accountNumber": "1234",
                "positions": positions,
            }
        }
    )


def test_wheel_summary_flags_short_options_above_80_percent_profit():
    account = account_with_positions(
        [
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
            },
            {
                "shortQuantity": 1,
                "averagePrice": 2.0,
                "marketValue": -50.0,
                "instrument": {
                    "symbol": "MSFT  260424P00380000",
                    "assetType": "OPTION",
                    "putCall": "PUT",
                    "underlyingSymbol": "MSFT",
                    "expirationDate": "2026-04-24",
                    "strikePrice": 380,
                },
            },
        ]
    )

    summary = build_wheel_summary([account], as_of=date(2026, 4, 20))

    assert [row["underlying"] for row in summary.profit_targets] == ["AAPL"]
    assert summary.profit_targets[0]["profit_percent"] == 0.825
    assert summary.profit_targets[0]["cost_basis"] == 200.0
    assert summary.profit_targets[0]["current_value"] == 35.0
    assert summary.profit_loss["month_to_date"] == 0.0
    assert summary.balances == [
        {"account": "1234", "account_type": None, "available": False}
    ]


def test_wheel_summary_flags_options_expiring_in_next_five_days():
    account = account_with_positions(
        [
            {
                "shortQuantity": 1,
                "averagePrice": 1.0,
                "marketValue": -25.0,
                "instrument": {
                    "symbol": "AAPL  260423C00200000",
                    "assetType": "OPTION",
                    "putCall": "CALL",
                    "underlyingSymbol": "AAPL",
                    "expirationDate": "2026-04-23",
                    "strikePrice": 200,
                },
            },
            {
                "shortQuantity": 1,
                "averagePrice": 1.0,
                "marketValue": -25.0,
                "instrument": {
                    "symbol": "NVDA  260501P00800000",
                    "assetType": "OPTION",
                    "putCall": "PUT",
                    "underlyingSymbol": "NVDA",
                    "expirationDate": "2026-05-01",
                    "strikePrice": 800,
                },
            },
        ]
    )

    summary = build_wheel_summary([account], as_of=date(2026, 4, 20), expiry_days=5)

    assert [row["underlying"] for row in summary.expiring_soon] == ["AAPL"]
    assert summary.expiring_soon[0]["days_to_expiration"] == 3


def test_wheel_summary_ignores_non_option_positions():
    account = account_with_positions(
        [
            {
                "longQuantity": 10,
                "averagePrice": 100,
                "marketValue": 1200,
                "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
            }
        ]
    )

    summary = build_wheel_summary([account], as_of=date(2026, 4, 20))

    assert summary.profit_targets == []
    assert summary.expiring_soon == []


def test_parse_expiration_date_falls_back_to_osi_symbol():
    expiration = parse_expiration_date(None, "AAPL  260424P00180000")

    assert expiration == date(2026, 4, 24)


def test_build_account_balances_uses_current_balances():
    account = Account.model_validate(
        {
            "securitiesAccount": {
                "accountNumber": "1234",
                "type": "MARGIN",
                "currentBalances": {
                    "cashBalance": 1234.567,
                    "cashAvailableForTrading": 1200,
                    "buyingPower": 8000,
                    "optionBuyingPower": 6000,
                    "liquidationValue": 25000,
                    "longMarketValue": 20000,
                    "shortMarketValue": -3000,
                    "maintenanceRequirement": 5000,
                    "maintenanceCall": 0,
                    "availableFunds": 7000,
                    "availableFundsNonMarginableTrade": 6500,
                },
            }
        }
    )

    balances = build_account_balances([account])

    assert balances == [
        {
            "account": "1234",
            "account_type": "MARGIN",
            "available": True,
            "cash_balance": 1234.57,
            "cash_available_for_trading": 1200,
            "buying_power": 8000,
            "option_buying_power": 6000,
            "liquidation_value": 25000,
            "long_market_value": 20000,
            "short_market_value": -3000,
            "maintenance_requirement": 5000,
            "maintenance_call": 0,
            "available_funds": 7000,
            "available_funds_non_marginable_trade": 6500,
        }
    ]
