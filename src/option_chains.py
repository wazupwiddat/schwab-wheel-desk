from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional

from .models import OptionChain, OptionContract


def option_chain_window(as_of: Optional[date] = None, max_days: int = 44):
    as_of = as_of or date.today()
    return as_of, as_of + timedelta(days=max_days)


def summarize_option_chain(
    chain: OptionChain,
    as_of: Optional[date] = None,
    max_days: int = 44,
    strike_pct: float = 0.15,
) -> Dict[str, Any]:
    as_of = as_of or date.today()
    strike_pct = normalize_strike_pct(strike_pct)
    underlying_price = resolve_underlying_price(chain)
    if underlying_price is None:
        raise RuntimeError("Option chain response did not include an underlying price.")

    min_strike = underlying_price * (1 - strike_pct)
    max_strike = underlying_price * (1 + strike_pct)
    contracts = [
        row
        for row in flatten_option_chain(chain)
        if should_include_contract(row, as_of, max_days, min_strike, max_strike)
    ]

    contracts.sort(
        key=lambda row: (
            row["expiration_date"] or "",
            row["strike_price"] if row["strike_price"] is not None else 0,
            row["put_call"] or "",
        )
    )

    return {
        "symbol": chain.symbol,
        "underlying_price": round(underlying_price, 4),
        "filters": {
            "max_days": max_days,
            "strike_pct": strike_pct,
            "min_strike": round(min_strike, 4),
            "max_strike": round(max_strike, 4),
        },
        "contract_count": len(contracts),
        "contracts": contracts,
    }


def normalize_strike_pct(value: float) -> float:
    if value < 0:
        raise ValueError("strike_pct must be non-negative")
    if value > 1:
        return value / 100
    return value


def resolve_underlying_price(chain: OptionChain) -> Optional[float]:
    if chain.underlying_price is not None:
        return chain.underlying_price

    for key in ("mark", "last", "close", "bid", "ask"):
        value = chain.underlying.get(key)
        if value is not None:
            return float(value)
    return None


def flatten_option_chain(chain: OptionChain) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    rows.extend(flatten_expiration_map(chain.call_exp_date_map, "CALL"))
    rows.extend(flatten_expiration_map(chain.put_exp_date_map, "PUT"))
    return rows


def flatten_expiration_map(
    expiration_map: Dict[str, Dict[str, List[OptionContract]]], put_call: str
) -> Iterable[Dict[str, Any]]:
    for expiration_key, strike_map in expiration_map.items():
        expiration_date, days_from_key = parse_expiration_key(expiration_key)
        for strike, contracts in strike_map.items():
            for contract in contracts:
                yield contract_row(
                    contract=contract,
                    fallback_put_call=put_call,
                    fallback_strike=strike,
                    fallback_expiration_date=expiration_date,
                    fallback_days_to_expiration=days_from_key,
                )


def contract_row(
    contract: OptionContract,
    fallback_put_call: str,
    fallback_strike: str,
    fallback_expiration_date: Optional[date],
    fallback_days_to_expiration: Optional[int],
) -> Dict[str, Any]:
    expiration = parse_contract_expiration(contract, fallback_expiration_date)
    strike_price = contract.strike_price
    if strike_price is None:
        strike_price = float(fallback_strike)

    return {
        "put_call": contract.put_call or fallback_put_call,
        "symbol": contract.symbol,
        "description": contract.description,
        "strike_price": strike_price,
        "expiration_date": expiration.isoformat() if expiration else None,
        "days_to_expiration": contract.days_to_expiration
        if contract.days_to_expiration is not None
        else fallback_days_to_expiration,
        "bid": contract.bid,
        "ask": contract.ask,
        "last": contract.last,
        "mark": contract.mark,
        "delta": contract.delta,
        "theta": contract.theta,
        "open_interest": contract.open_interest,
        "volume": contract.total_volume,
        "in_the_money": contract.in_the_money,
    }


def should_include_contract(
    row: Dict[str, Any],
    as_of: date,
    max_days: int,
    min_strike: float,
    max_strike: float,
) -> bool:
    strike_price = row.get("strike_price")
    expiration = parse_date(row.get("expiration_date"))
    if strike_price is None or expiration is None:
        return False

    days_to_expiration = (expiration - as_of).days
    return 0 <= days_to_expiration <= max_days and min_strike <= strike_price <= max_strike


def parse_expiration_key(value: str):
    date_part, _, days_part = value.partition(":")
    expiration = parse_date(date_part)
    days_to_expiration = int(days_part) if days_part.isdigit() else None
    return expiration, days_to_expiration


def parse_contract_expiration(
    contract: OptionContract, fallback: Optional[date]
) -> Optional[date]:
    if contract.expiration_date:
        return parse_date(contract.expiration_date[:10])
    return fallback


def parse_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
