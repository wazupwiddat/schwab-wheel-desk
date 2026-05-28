from datetime import date

from src.models import Account, OptionChain, Transaction
from src.wheel_agent import (
    WheelAgentRules,
    build_cash_guardrails,
    build_wheel_recommendations,
    discover_symbols,
    load_symbol_file,
)


def account(payload):
    return Account.model_validate(payload)


def chain(symbol, underlying_price=100.0):
    return OptionChain.model_validate(
        {
            "symbol": symbol,
            "underlyingPrice": underlying_price,
            "callExpDateMap": {
                "2026-05-15:24": {
                    "110.0": [
                        {
                            "putCall": "CALL",
                            "symbol": f"{symbol}  260515C00110000",
                            "strikePrice": 110,
                            "expirationDate": "2026-05-15",
                            "bid": 3.5,
                            "mark": 3.6,
                            "delta": 0.25,
                        }
                    ]
                }
            },
            "putExpDateMap": {
                "2026-05-15:24": {
                    "90.0": [
                        {
                            "putCall": "PUT",
                            "symbol": f"{symbol}  260515P00090000",
                            "strikePrice": 90,
                            "expirationDate": "2026-05-15",
                            "bid": 3.0,
                            "mark": 3.1,
                            "delta": -0.25,
                        }
                    ]
                }
            },
        }
    )


def test_discover_symbols_uses_only_file_symbols_when_present():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "positions": [
                        {
                            "longQuantity": 100,
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ]
                }
            }
        )
    ]
    transactions = [
        Transaction.from_payload(
            {
                "transactionItem": {
                    "instrument": {
                        "symbol": "MSFT  260515P00300000",
                        "assetType": "OPTION",
                    }
                }
            }
        )
    ]

    symbols = discover_symbols(accounts, transactions, stored_symbols=["NVDA"])

    assert symbols == {"NVDA"}


def test_discover_symbols_falls_back_to_positions_and_transactions_when_file_empty():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "positions": [
                        {
                            "longQuantity": 100,
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ]
                }
            }
        )
    ]
    transactions = [
        Transaction.from_payload(
            {
                "transactionItem": {
                    "instrument": {
                        "symbol": "MSFT  260515P00300000",
                        "assetType": "OPTION",
                    }
                }
            }
        )
    ]

    symbols = discover_symbols(accounts, transactions, stored_symbols=[])

    assert symbols == {"AAPL", "MSFT"}


def test_cash_guardrails_keeps_cash_above_ten_percent_and_subtracts_open_csp():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 20000,
                        "liquidationValue": 100000,
                    },
                    "positions": [
                        {
                            "shortQuantity": 1,
                            "instrument": {
                                "assetType": "OPTION",
                                "putCall": "PUT",
                                "strikePrice": 50,
                            },
                        }
                    ],
                }
            }
        )
    ]

    guardrails = build_cash_guardrails(accounts, WheelAgentRules())

    assert guardrails["accounts"][0]["required_cash_reserve"] == 10000
    assert guardrails["accounts"][0]["open_cash_secured_put_collateral"] == 5000
    assert guardrails["accounts"][0]["remaining_csp_capacity"] == 5000


def test_build_wheel_recommendations_suggests_calls_and_puts_that_match_rules():
    accounts = [
        account(
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
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ],
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL")},
        as_of=date(2026, 4, 21),
    )

    assert result["cash_guardrails"]["aggregate"]["remaining_csp_capacity"] == 40000
    assert result["recommendations"]["covered_calls"][0]["action"] == "SELL_COVERED_CALL"
    assert result["recommendations"]["cash_secured_puts"][0]["action"] == "SELL_CASH_SECURED_PUT"
    assert result["recommendations"]["covered_calls"][0]["account"] == "1234"
    assert result["recommendations"]["cash_secured_puts"][0]["account"] == "1234"
    assert result["recommendations"]["cash_secured_puts"][0]["available_cash_in_account"] == 40000
    assert result["rules"]["max_call_delta"] == 0.35
    assert result["rules"]["min_call_premium_pct"] == 0.025
    assert result["rules"]["min_put_delta"] == -0.25
    assert result["rules"]["min_put_premium_pct"] == 0.03


def test_build_wheel_recommendations_rejects_put_delta_below_negative_point_two_five():
    bad_chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100,
            "callExpDateMap": {},
            "putExpDateMap": {
                "2026-05-15:24": {
                    "90.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "AAPL  260515P00090000",
                            "strikePrice": 90,
                            "expirationDate": "2026-05-15",
                            "bid": 3.0,
                            "delta": -0.26,
                        }
                    ]
                }
            },
        }
    )
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": bad_chain},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["cash_secured_puts"] == []
    assert result["recommendations"]["cash_secured_put_closest_miss"]["action"] == (
        "CLOSEST_MISS_CASH_SECURED_PUT"
    )
    assert (
        result["recommendations"]["cash_secured_put_closest_miss"]["contract"]["symbol"]
        == "AAPL  260515P00090000"
    )
    assert result["recommendations"]["by_account"][0]["cash_secured_put_closest_miss"][
        "contract"
    ]["symbol"] == "AAPL  260515P00090000"


def test_build_wheel_recommendations_accepts_covered_call_with_higher_delta_and_lower_premium():
    accounts = [
        account(
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
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ],
                }
            }
        )
    ]
    adjusted_chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100,
            "callExpDateMap": {
                "2026-05-15:24": {
                    "110.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260515C00110000",
                            "strikePrice": 110,
                            "expirationDate": "2026-05-15",
                            "bid": 2.8,
                            "delta": 0.34,
                        }
                    ]
                }
            },
            "putExpDateMap": {},
        }
    )

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": adjusted_chain},
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["covered_calls"][0]["contract"]["delta"] == 0.34


def test_build_wheel_recommendations_skips_covered_call_when_short_call_already_exists():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                    "positions": [
                        {
                            "longQuantity": 600,
                            "averagePrice": 80,
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        },
                        {
                            "shortQuantity": 5,
                            "instrument": {
                                "symbol": "AAPL  260515C00110000",
                                "assetType": "OPTION",
                                "putCall": "CALL",
                                "underlyingSymbol": "AAPL",
                            },
                        },
                    ],
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL")},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["covered_calls"] == []


def test_build_wheel_recommendations_skips_put_when_short_put_already_exists():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                    "positions": [
                        {
                            "shortQuantity": 1,
                            "instrument": {
                                "symbol": "AAPL  260515P00090000",
                                "assetType": "OPTION",
                                "putCall": "PUT",
                                "underlyingSymbol": "AAPL",
                                "strikePrice": 90,
                            },
                        }
                    ],
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL")},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["cash_secured_puts"] == []
    assert result["recommendations"]["cash_secured_put_closest_miss"] is None


def test_build_wheel_recommendations_skips_put_when_cash_required_is_100k_or_more():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 250000,
                        "liquidationValue": 300000,
                    },
                }
            }
        )
    ]
    expensive_put_chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100,
            "callExpDateMap": {},
            "putExpDateMap": {
                "2026-05-15:24": {
                    "1000.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "AAPL  260515P01000000",
                            "strikePrice": 1000,
                            "expirationDate": "2026-05-15",
                            "bid": 40.0,
                            "delta": -0.2,
                        }
                    ]
                }
            },
        }
    )

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": expensive_put_chain},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["cash_secured_puts"] == []
    assert result["recommendations"]["cash_secured_put_closest_miss"] is None


def test_build_wheel_recommendations_prefers_real_csp_matches_over_closest_miss():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL")},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["cash_secured_puts"][0]["action"] == "SELL_CASH_SECURED_PUT"
    assert result["recommendations"]["cash_secured_put_closest_miss"] is None


def test_build_wheel_recommendations_only_shows_covered_calls_for_account_with_shares():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1111",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                    "positions": [
                        {
                            "longQuantity": 100,
                            "averagePrice": 80,
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ],
                }
            }
        ),
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "2222",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                    "positions": [],
                }
            }
        ),
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL")},
        stored_symbols=["AAPL"],
        as_of=date(2026, 4, 21),
    )

    assert {row["account"] for row in result["recommendations"]["covered_calls"]} == {"1111"}
    grouped = {
        row["account"]: row for row in result["recommendations"]["by_account"]
    }
    assert grouped["1111"]["covered_calls"]
    assert grouped["2222"]["covered_calls"] == []


def test_build_wheel_recommendations_sorts_covered_calls_by_dte_then_premium_then_lower_delta():
    accounts = [
        account(
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
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        }
                    ],
                }
            }
        )
    ]
    sorted_chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100,
            "callExpDateMap": {
                "2026-05-15:24": {
                    "110.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260515C00110000",
                            "strikePrice": 110,
                            "expirationDate": "2026-05-15",
                            "bid": 3.4,
                            "delta": 0.31,
                        }
                    ],
                    "111.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260515C00111000",
                            "strikePrice": 111,
                            "expirationDate": "2026-05-15",
                            "bid": 3.4,
                            "delta": 0.29,
                        }
                    ],
                },
                "2026-05-22:31": {
                    "110.0": [
                        {
                            "putCall": "CALL",
                            "symbol": "AAPL  260522C00110000",
                            "strikePrice": 110,
                            "expirationDate": "2026-05-22",
                            "bid": 5.0,
                            "delta": 0.2,
                        }
                    ]
                },
            },
            "putExpDateMap": {},
        }
    )

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": sorted_chain},
        as_of=date(2026, 4, 21),
    )

    symbols = [row["contract"]["symbol"] for row in result["recommendations"]["covered_calls"]]
    assert symbols == [
        "AAPL  260515C00111000",
        "AAPL  260515C00110000",
        "AAPL  260522C00110000",
    ]


def test_build_wheel_recommendations_sorts_puts_by_dte_then_premium_then_higher_delta():
    accounts = [
        account(
            {
                "securitiesAccount": {
                    "accountNumber": "1234",
                    "currentBalances": {
                        "cashBalance": 50000,
                        "liquidationValue": 100000,
                    },
                }
            }
        )
    ]
    sorted_chain = OptionChain.model_validate(
        {
            "symbol": "AAPL",
            "underlyingPrice": 100,
            "callExpDateMap": {},
            "putExpDateMap": {
                "2026-05-15:24": {
                    "90.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "AAPL  260515P00090000",
                            "strikePrice": 90,
                            "expirationDate": "2026-05-15",
                            "bid": 3.0,
                            "delta": -0.2,
                        }
                    ],
                    "91.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "AAPL  260515P00091000",
                            "strikePrice": 91,
                            "expirationDate": "2026-05-15",
                            "bid": 3.0,
                            "delta": -0.1,
                        }
                    ],
                },
            },
        }
    )
    msft_chain = OptionChain.model_validate(
        {
            "symbol": "MSFT",
            "underlyingPrice": 100,
            "callExpDateMap": {},
            "putExpDateMap": {
                "2026-05-22:31": {
                    "90.0": [
                        {
                            "putCall": "PUT",
                            "symbol": "MSFT  260522P00090000",
                            "strikePrice": 90,
                            "expirationDate": "2026-05-22",
                            "bid": 4.0,
                            "delta": -0.15,
                        }
                    ]
                }
            },
        }
    )

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": sorted_chain, "MSFT": msft_chain},
        stored_symbols=["AAPL", "MSFT"],
        as_of=date(2026, 4, 21),
    )

    symbols = [row["contract"]["symbol"] for row in result["recommendations"]["cash_secured_puts"]]
    assert symbols == [
        "AAPL  260515P00091000",
        "MSFT  260522P00090000",
    ]


def test_build_wheel_recommendations_suggests_roll_for_itm_short_option():
    accounts = [
        account(
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
                            "averagePrice": 120,
                            "instrument": {"symbol": "AAPL", "assetType": "EQUITY"},
                        },
                        {
                            "shortQuantity": 1,
                            "marketValue": -100,
                            "instrument": {
                                "symbol": "AAPL  260424C00090000",
                                "assetType": "OPTION",
                                "putCall": "CALL",
                                "underlyingSymbol": "AAPL",
                                "expirationDate": "2026-04-24",
                                "strikePrice": 90,
                            },
                        },
                    ],
                }
            }
        )
    ]

    result = build_wheel_recommendations(
        accounts=accounts,
        transactions=[],
        option_chains={"AAPL": chain("AAPL", underlying_price=100)},
        as_of=date(2026, 4, 21),
    )

    assert result["recommendations"]["rolls"][0]["action"] == "ROLL_SHORT_OPTION"


def test_load_symbol_file_ignores_comments(tmp_path):
    path = tmp_path / "symbols.txt"
    path.write_text("aapl\n# nope\n msft # comment\n", encoding="utf-8")

    assert load_symbol_file(path) == ["AAPL", "MSFT"]
