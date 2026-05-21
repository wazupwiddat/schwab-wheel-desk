from datetime import date

from src.models import OptionChain
from src.option_chains import (
    normalize_strike_pct,
    option_chain_window,
    summarize_option_chain,
)


def test_option_chain_window_defaults_to_less_than_45_days():
    from_date, to_date = option_chain_window(date(2026, 4, 21))

    assert from_date == date(2026, 4, 21)
    assert to_date == date(2026, 6, 4)


def test_summarize_option_chain_filters_expiration_and_strike_distance():
    chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100.0,
            "callExpDateMap": {
                "2026-05-01:10": {
                    "85.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260501C00085000",
                            "strikePrice": 85.0,
                            "expirationDate": "2026-05-01",
                            "bid": 16.0,
                            "ask": 17.0,
                        }
                    ],
                    "116.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260501C00116000",
                            "strikePrice": 116.0,
                            "expirationDate": "2026-05-01",
                        }
                    ],
                },
                "2026-06-10:50": {
                    "100.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260610C00100000",
                            "strikePrice": 100.0,
                            "expirationDate": "2026-06-10",
                        }
                    ]
                },
            },
            "putExpDateMap": {
                "2026-05-01:10": {
                    "95.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "AAPL  260501P00095000",
                            "strikePrice": 95.0,
                            "expirationDate": "2026-05-01",
                        }
                    ]
                }
            },
        }
    )

    summary = summarize_option_chain(
        chain,
        as_of=date(2026, 4, 21),
        max_days=44,
        strike_pct=0.15,
    )

    assert summary["filters"]["min_strike"] == 85.0
    assert summary["filters"]["max_strike"] == 115.0
    assert summary["contract_count"] == 2
    assert [contract["symbol"] for contract in summary["contracts"]] == [
        "AAPL  260501C00085000",
        "AAPL  260501P00095000",
    ]


def test_normalize_strike_pct_accepts_fraction_or_percent():
    assert normalize_strike_pct(0.15) == 0.15
    assert normalize_strike_pct(15) == 0.15
