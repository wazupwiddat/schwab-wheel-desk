from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from .models import Account, OptionChain, Position, Transaction
from .option_chains import flatten_option_chain, parse_date, resolve_underlying_price
from .wheel_summary import parse_expiration_date, transaction_items


CONTRACT_MULTIPLIER = 100


@dataclass(frozen=True)
class WheelAgentRules:
    reserve_cash_pct: float = 0.10
    min_call_premium_pct: float = 0.025
    min_put_premium_pct: float = 0.03
    max_call_delta: float = 0.35
    min_put_delta: float = -0.25
    max_cash_secured_put_requirement: float = 100000.0
    max_dte: int = 31
    min_roll_premium_pct: float = 0.02


def build_wheel_recommendations(
    accounts: List[Account],
    transactions: List[Transaction],
    option_chains: Dict[str, OptionChain],
    stored_symbols: Optional[Iterable[str]] = None,
    as_of: Optional[date] = None,
    rules: WheelAgentRules = WheelAgentRules(),
) -> Dict[str, Any]:
    as_of = as_of or date.today()
    symbols = sorted(discover_symbols(accounts, transactions, stored_symbols))
    cash_guardrails = build_cash_guardrails(accounts, rules)
    equity_positions = build_equity_positions(accounts)
    equity_positions_by_account = build_equity_positions_by_account(accounts)
    short_option_symbols_by_account = build_short_option_symbols_by_account(accounts)
    cash_guardrails_by_account = {
        row["account"]: row for row in cash_guardrails["accounts"] if row.get("account")
    }
    short_options = build_short_options(accounts, as_of)

    covered_calls = build_covered_call_recommendations(
        equity_positions_by_account=equity_positions_by_account,
        short_option_symbols_by_account=short_option_symbols_by_account,
        option_chains=option_chains,
        as_of=as_of,
        rules=rules,
    )
    cash_secured_puts, cash_secured_put_closest_misses = build_cash_secured_put_recommendations(
        accounts=accounts,
        symbols=symbols,
        short_option_symbols_by_account=short_option_symbols_by_account,
        option_chains=option_chains,
        cash_guardrails_by_account=cash_guardrails_by_account,
        as_of=as_of,
        rules=rules,
    )
    rolls = build_roll_recommendations(
        short_options=short_options,
        equity_positions=equity_positions,
        option_chains=option_chains,
        as_of=as_of,
        rules=rules,
    )

    return {
        "as_of": as_of.isoformat(),
        "rules": {
            "reserve_cash_pct": rules.reserve_cash_pct,
            "min_call_premium_pct": rules.min_call_premium_pct,
            "min_put_premium_pct": rules.min_put_premium_pct,
            "max_call_delta": rules.max_call_delta,
            "min_put_delta": rules.min_put_delta,
            "max_cash_secured_put_requirement": rules.max_cash_secured_put_requirement,
            "max_dte": rules.max_dte,
            "min_roll_premium_pct": rules.min_roll_premium_pct,
        },
        "symbols": symbols,
        "cash_guardrails": cash_guardrails,
        "recommendations": {
            "rolls": rolls,
            "covered_calls": covered_calls,
            "cash_secured_puts": cash_secured_puts,
            "cash_secured_put_closest_miss": (
                sorted_closest_misses(cash_secured_put_closest_misses)[0]
                if not cash_secured_puts and cash_secured_put_closest_misses
                else None
            ),
            "by_account": recommendations_by_account(
                accounts=accounts,
                covered_calls=covered_calls,
                cash_secured_puts=cash_secured_puts,
                cash_secured_put_closest_misses=cash_secured_put_closest_misses,
                rolls=rolls,
            ),
        },
        "notes": [
            "Read-only suggestions only; no orders are placed.",
            "Cash-secured put ideas are capped by cash above the 10% reserve.",
            "Tradability is inferred by whether Schwab returns option-chain data.",
        ],
    }


def load_symbol_file(path: Path) -> List[str]:
    if not path.exists():
        return []
    symbols: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.split("#", 1)[0].strip().upper()
        if value:
            symbols.append(value)
    return symbols


def discover_symbols(
    accounts: List[Account],
    transactions: List[Transaction],
    stored_symbols: Optional[Iterable[str]] = None,
) -> Set[str]:
    explicit_symbols = {symbol.upper() for symbol in stored_symbols or [] if symbol}
    if explicit_symbols:
        return explicit_symbols

    symbols: Set[str] = set()

    for account in accounts:
        for position in account.securities_account.positions:
            symbol = position_underlying_symbol(position)
            if symbol:
                symbols.add(symbol)

    for transaction in transactions:
        for item in transaction_items(transaction):
            instrument = item.instrument
            if instrument is None:
                continue
            symbol = instrument.underlying_symbol or instrument.symbol
            symbol = normalize_trade_symbol(symbol, instrument.asset_type)
            if symbol:
                symbols.add(symbol)

    return symbols


def build_cash_guardrails(
    accounts: List[Account], rules: WheelAgentRules
) -> Dict[str, Any]:
    account_rows: List[Dict[str, Any]] = []
    total_cash = 0.0
    total_value = 0.0
    total_required_reserve = 0.0
    total_open_csp_collateral = 0.0

    for account in accounts:
        securities_account = account.securities_account
        balances = (
            securities_account.current_balances
            or securities_account.projected_balances
            or securities_account.initial_balances
        )
        cash = balances.cash_balance if balances and balances.cash_balance is not None else 0.0
        value = (
            balances.liquidation_value
            if balances and balances.liquidation_value is not None
            else 0.0
        )
        reserve = value * rules.reserve_cash_pct
        open_csp_collateral = open_cash_secured_put_collateral(
            securities_account.positions
        )
        remaining_capacity = max(cash - reserve - open_csp_collateral, 0.0)

        total_cash += cash
        total_value += value
        total_required_reserve += reserve
        total_open_csp_collateral += open_csp_collateral

        account_rows.append(
            {
                "account": securities_account.account_number,
                "cash_balance": round(cash, 2),
                "liquidation_value": round(value, 2),
                "required_cash_reserve": round(reserve, 2),
                "open_cash_secured_put_collateral": round(open_csp_collateral, 2),
                "remaining_csp_capacity": round(remaining_capacity, 2),
                "reserve_ok": cash >= reserve,
            }
        )

    return {
        "accounts": account_rows,
        "aggregate": {
            "cash_balance": round(total_cash, 2),
            "liquidation_value": round(total_value, 2),
            "required_cash_reserve": round(total_required_reserve, 2),
            "open_cash_secured_put_collateral": round(total_open_csp_collateral, 2),
            "remaining_csp_capacity": round(
                max(total_cash - total_required_reserve - total_open_csp_collateral, 0.0),
                2,
            ),
            "reserve_ok": total_cash >= total_required_reserve,
        },
    }


def open_cash_secured_put_collateral(positions: List[Position]) -> float:
    total = 0.0
    for position in positions:
        instrument = position.instrument
        if (
            instrument
            and instrument.asset_type == "OPTION"
            and instrument.put_call == "PUT"
            and position.short_quantity
            and instrument.strike_price
        ):
            total += position.short_quantity * instrument.strike_price * CONTRACT_MULTIPLIER
    return total


def build_equity_positions(accounts: List[Account]) -> Dict[str, Dict[str, Any]]:
    positions: Dict[str, Dict[str, Any]] = {}
    for account in accounts:
        account_number = account.securities_account.account_number
        for position in account.securities_account.positions:
            instrument = position.instrument
            if not instrument or instrument.asset_type != "EQUITY" or not instrument.symbol:
                continue
            if not position.long_quantity:
                continue
            symbol = instrument.symbol.upper()
            row = positions.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "accounts": [],
                    "quantity": 0.0,
                    "average_price": position.average_price,
                },
            )
            row["accounts"].append(account_number)
            row["quantity"] += position.long_quantity
            if row["average_price"] is None and position.average_price is not None:
                row["average_price"] = position.average_price
    return positions


def build_equity_positions_by_account(
    accounts: List[Account],
) -> Dict[str, Dict[str, Dict[str, Any]]]:
    rows: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for account in accounts:
        account_number = account.securities_account.account_number
        account_positions = rows.setdefault(account_number, {})
        for position in account.securities_account.positions:
            instrument = position.instrument
            if not instrument or instrument.asset_type != "EQUITY" or not instrument.symbol:
                continue
            if not position.long_quantity:
                continue
            symbol = instrument.symbol.upper()
            row = account_positions.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "account": account_number,
                    "quantity": 0.0,
                    "average_price": position.average_price,
                },
            )
            row["quantity"] += position.long_quantity
            if row["average_price"] is None and position.average_price is not None:
                row["average_price"] = position.average_price
    return rows


def build_short_options(accounts: List[Account], as_of: date) -> List[Dict[str, Any]]:
    options: List[Dict[str, Any]] = []
    for account in accounts:
        for position in account.securities_account.positions:
            instrument = position.instrument
            if (
                not instrument
                or instrument.asset_type != "OPTION"
                or not position.short_quantity
            ):
                continue
            expiration = parse_expiration_date(
                instrument.expiration_date, instrument.symbol
            )
            options.append(
                {
                    "account": account.securities_account.account_number,
                    "symbol": instrument.symbol,
                    "underlying": position_underlying_symbol(position),
                    "put_call": instrument.put_call,
                    "strike_price": instrument.strike_price,
                    "expiration_date": expiration.isoformat() if expiration else None,
                    "days_to_expiration": (expiration - as_of).days if expiration else None,
                    "quantity": position.short_quantity,
                    "average_price": position.average_price,
                    "market_value": position.market_value,
                }
            )
    return options


def build_short_option_symbols_by_account(
    accounts: List[Account],
) -> Dict[str, Dict[str, Set[str]]]:
    rows: Dict[str, Dict[str, Set[str]]] = {}
    for account in accounts:
        account_number = account.securities_account.account_number
        symbols_by_type = rows.setdefault(account_number, {"CALL": set(), "PUT": set()})
        for position in account.securities_account.positions:
            instrument = position.instrument
            if (
                not instrument
                or instrument.asset_type != "OPTION"
                or not position.short_quantity
                or not instrument.put_call
            ):
                continue
            underlying = position_underlying_symbol(position)
            if underlying:
                symbols_by_type.setdefault(instrument.put_call, set()).add(underlying)
    return rows


def build_covered_call_recommendations(
    equity_positions_by_account: Dict[str, Dict[str, Dict[str, Any]]],
    short_option_symbols_by_account: Dict[str, Dict[str, Set[str]]],
    option_chains: Dict[str, OptionChain],
    as_of: date,
    rules: WheelAgentRules,
) -> List[Dict[str, Any]]:
    recommendations: List[Dict[str, Any]] = []
    for account_number, positions in equity_positions_by_account.items():
        account_short_calls = short_option_symbols_by_account.get(account_number, {}).get(
            "CALL", set()
        )
        for symbol, position in positions.items():
            contracts_available = int(position["quantity"] // CONTRACT_MULTIPLIER)
            if (
                contracts_available <= 0
                or symbol not in option_chains
                or symbol in account_short_calls
            ):
                continue
            underlying_price = resolve_underlying_price(option_chains[symbol])
            for contract in eligible_contracts(
                option_chains[symbol], "CALL", as_of, rules.max_dte
            ):
                if not meets_call_rule(contract, rules):
                    continue
                recommendations.append(
                    recommendation_row(
                        action="SELL_COVERED_CALL",
                        symbol=symbol,
                        contract=contract,
                        underlying_price=underlying_price,
                        max_contracts=contracts_available,
                        reason="Premium is at least 2.5% of strike and call delta is within rule.",
                        extra={"account": account_number},
                    )
                )
    return sorted_recommendations(recommendations, action="SELL_COVERED_CALL")


def build_cash_secured_put_recommendations(
    accounts: List[Account],
    symbols: List[str],
    short_option_symbols_by_account: Dict[str, Dict[str, Set[str]]],
    option_chains: Dict[str, OptionChain],
    cash_guardrails_by_account: Dict[str, Dict[str, Any]],
    as_of: date,
    rules: WheelAgentRules,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    recommendations: List[Dict[str, Any]] = []
    closest_misses: List[Dict[str, Any]] = []
    remaining_cash_by_account = {
        account.securities_account.account_number: (
            cash_guardrails_by_account.get(account.securities_account.account_number, {}).get(
                "remaining_csp_capacity", 0.0
            )
            or 0.0
        )
        for account in accounts
    }

    for account in accounts:
        account_number = account.securities_account.account_number
        available_cash = remaining_cash_by_account.get(account_number, 0.0)
        account_short_puts = short_option_symbols_by_account.get(account_number, {}).get(
            "PUT", set()
        )
        account_closest_misses: List[Dict[str, Any]] = []
        for symbol in symbols:
            if symbol not in option_chains or symbol in account_short_puts:
                continue
            underlying_price = resolve_underlying_price(option_chains[symbol])
            all_put_contracts = eligible_contracts(
                option_chains[symbol], "PUT", as_of, rules.max_dte
            )
            eligible = [contract for contract in all_put_contracts if meets_put_rule(contract, rules)]
            eligible = sorted_recommendations(
                [
                    recommendation_row(
                        action="SELL_CASH_SECURED_PUT",
                        symbol=symbol,
                        contract=contract,
                        underlying_price=underlying_price,
                        max_contracts=1,
                        reason="Premium is at least 3% of strike, put delta is between -0.25 and 0, and cash reserve stays intact.",
                        extra={
                            "account": account_number,
                            "cash_required": round(
                                (contract["strike_price"] or 0) * CONTRACT_MULTIPLIER, 2
                            ),
                            "available_cash_in_account": round(available_cash, 2),
                        },
                    )
                    for contract in eligible
                ],
                action="SELL_CASH_SECURED_PUT",
            )
            for row in eligible:
                collateral = row["cash_required"]
                if (
                    collateral >= rules.max_cash_secured_put_requirement
                    or collateral > available_cash
                ):
                    continue
                recommendations.append(row)
                available_cash -= collateral
                remaining_cash_by_account[account_number] = available_cash
                break
            if eligible:
                continue
            closest_contract = closest_put_miss_contract(
                contracts=all_put_contracts,
                available_cash=available_cash,
                rules=rules,
            )
            if closest_contract is None:
                continue
            account_closest_misses.append(
                closest_miss_row(
                    symbol=symbol,
                    account=account_number,
                    contract=closest_contract,
                    underlying_price=underlying_price,
                    available_cash=available_cash,
                    rules=rules,
                )
            )
        if not any(row.get("account") == account_number for row in recommendations) and account_closest_misses:
            closest_misses.append(sorted_closest_misses(account_closest_misses)[0])
    return sorted_recommendations(recommendations, action="SELL_CASH_SECURED_PUT"), sorted_closest_misses(closest_misses)


def recommendations_by_account(
    accounts: List[Account],
    covered_calls: List[Dict[str, Any]],
    cash_secured_puts: List[Dict[str, Any]],
    cash_secured_put_closest_misses: List[Dict[str, Any]],
    rolls: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    by_account: List[Dict[str, Any]] = []
    for account in accounts:
        account_number = account.securities_account.account_number
        by_account.append(
            {
                "account": account_number,
                "covered_calls": [
                    row for row in covered_calls if row.get("account") == account_number
                ],
                "cash_secured_puts": [
                    row
                    for row in cash_secured_puts
                    if row.get("account") == account_number
                ],
                "cash_secured_put_closest_miss": next(
                    (
                        row
                        for row in cash_secured_put_closest_misses
                        if row.get("account") == account_number
                    ),
                    None,
                ),
                "rolls": [
                    row
                    for row in rolls
                    if row.get("current_option", {}).get("account") == account_number
                ],
            }
        )
    return by_account


def contract_premium(contract: Dict[str, Any]) -> float:
    premium = contract.get("bid")
    if premium is None:
        premium = contract.get("mark") or 0
    return premium or 0.0


def put_delta_shortfall(contract: Dict[str, Any], rules: WheelAgentRules) -> float:
    delta = contract.get("delta")
    if delta is None:
        return 1_000_000.0
    if rules.min_put_delta <= delta <= 0:
        return 0.0
    if delta < rules.min_put_delta:
        return rules.min_put_delta - delta
    return delta


def put_premium_shortfall(contract: Dict[str, Any], rules: WheelAgentRules) -> float:
    return max(rules.min_put_premium_pct - premium_pct(contract), 0.0)


def closest_put_miss_contract(
    contracts: List[Dict[str, Any]],
    available_cash: float,
    rules: WheelAgentRules,
) -> Optional[Dict[str, Any]]:
    viable = []
    for contract in contracts:
        strike = contract.get("strike_price") or 0
        collateral = strike * CONTRACT_MULTIPLIER
        if (
            collateral >= rules.max_cash_secured_put_requirement
            or collateral > available_cash
        ):
            continue
        viable.append(contract)
    if not viable:
        return None
    return sorted(
        viable,
        key=lambda contract: (
            0 if put_premium_shortfall(contract, rules) > 0 else 1,
            put_premium_shortfall(contract, rules) + put_delta_shortfall(contract, rules),
            put_premium_shortfall(contract, rules),
            put_delta_shortfall(contract, rules),
            contract.get("days_to_expiration")
            if contract.get("days_to_expiration") is not None
            else 10**9,
            -contract_premium(contract),
            -(contract.get("delta") if contract.get("delta") is not None else -10**9),
        ),
    )[0]


def closest_miss_row(
    symbol: str,
    account: str,
    contract: Dict[str, Any],
    underlying_price: Optional[float],
    available_cash: float,
    rules: WheelAgentRules,
) -> Dict[str, Any]:
    premium_gap = put_premium_shortfall(contract, rules)
    delta_gap = put_delta_shortfall(contract, rules)
    reasons = []
    if premium_gap > 0:
        reasons.append(
            f"premium short by {round(premium_gap * 100, 2)} percentage points"
        )
    if delta_gap > 0:
        reasons.append(f"delta short by {round(delta_gap, 3)}")
    if not reasons:
        reasons.append("closest tradable miss")
    return {
        "action": "CLOSEST_MISS_CASH_SECURED_PUT",
        "account": account,
        "underlying": symbol,
        "underlying_price": rounded(underlying_price),
        "contract": contract_summary(contract),
        "cash_required": round((contract.get("strike_price") or 0) * CONTRACT_MULTIPLIER, 2),
        "available_cash_in_account": round(available_cash, 2),
        "premium_pct_of_strike": rounded(premium_pct(contract), 4),
        "delta_gap": rounded(delta_gap, 4),
        "premium_pct_gap": rounded(premium_gap, 4),
        "reason": "Closest miss for CSP criteria.",
        "miss_reasons": reasons,
    }


def sorted_closest_misses(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("premium_pct_gap") == 0,
            (row.get("premium_pct_gap") or 0) + (row.get("delta_gap") or 0),
            row.get("premium_pct_gap") or 0,
            row.get("delta_gap") or 0,
            row.get("contract", {}).get("days_to_expiration")
            if row.get("contract", {}).get("days_to_expiration") is not None
            else 10**9,
            -(row.get("contract", {}).get("bid") or 0),
            row.get("underlying") or "",
            row.get("account") or "",
        ),
    )


def sorted_recommendations(
    rows: List[Dict[str, Any]], action: Optional[str] = None
) -> List[Dict[str, Any]]:
    if action == "SELL_COVERED_CALL":
        return sorted(
            rows,
            key=lambda row: (
                row.get("contract", {}).get("days_to_expiration")
                if row.get("contract", {}).get("days_to_expiration") is not None
                else 10**9,
                -contract_premium(row.get("contract", {})),
                row.get("contract", {}).get("delta")
                if row.get("contract", {}).get("delta") is not None
                else 10**9,
                row.get("underlying") or "",
                row.get("account") or "",
            ),
        )
    if action == "SELL_CASH_SECURED_PUT":
        return sorted(
            rows,
            key=lambda row: (
                row.get("contract", {}).get("days_to_expiration")
                if row.get("contract", {}).get("days_to_expiration") is not None
                else 10**9,
                -contract_premium(row.get("contract", {})),
                -(
                    row.get("contract", {}).get("delta")
                    if row.get("contract", {}).get("delta") is not None
                    else -10**9
                ),
                row.get("underlying") or "",
                row.get("account") or "",
            ),
        )
    if action == "ROLL_SHORT_OPTION":
        return sorted(
            rows,
            key=lambda row: (
                row.get("roll_to", {}).get("days_to_expiration")
                if row.get("roll_to", {}).get("days_to_expiration") is not None
                else 10**9,
                -contract_premium(row.get("roll_to", {})),
                row.get("underlying") or "",
            ),
        )
    return sorted(rows, key=lambda row: row.get("underlying") or "")


def build_roll_recommendations(
    short_options: List[Dict[str, Any]],
    equity_positions: Dict[str, Dict[str, Any]],
    option_chains: Dict[str, OptionChain],
    as_of: date,
    rules: WheelAgentRules,
) -> List[Dict[str, Any]]:
    recommendations: List[Dict[str, Any]] = []
    for option in short_options:
        symbol = option.get("underlying")
        if not symbol or symbol not in option_chains:
            continue
        chain = option_chains[symbol]
        underlying_price = resolve_underlying_price(chain)
        if not is_short_option_itm(option, underlying_price):
            continue
        candidates = eligible_contracts(
            chain, option["put_call"], as_of, rules.max_dte
        )
        same_strike = [
            candidate
            for candidate in candidates
            if candidate["strike_price"] == option["strike_price"]
            and premium_pct(candidate) >= rules.min_roll_premium_pct
        ]
        directional = directional_roll_candidates(
            option,
            candidates,
            equity_positions.get(symbol),
            rules,
        )
        for candidate in (same_strike[:1] + directional[:1]):
            recommendations.append(
                roll_row(
                    option=option,
                    candidate=candidate,
                    underlying_price=underlying_price,
                    reason="In-the-money short option; roll candidate fits premium and DTE preference.",
                )
            )
    return sorted_recommendations(recommendations, action="ROLL_SHORT_OPTION")


def eligible_contracts(
    chain: OptionChain, put_call: str, as_of: date, max_dte: int
) -> List[Dict[str, Any]]:
    rows = []
    for contract in flatten_option_chain(chain):
        if contract.get("put_call") != put_call:
            continue
        expiration = parse_date(contract.get("expiration_date"))
        if expiration is None:
            continue
        days_to_expiration = (expiration - as_of).days
        if 0 < days_to_expiration <= max_dte:
            contract["days_to_expiration"] = days_to_expiration
            rows.append(contract)
    return rows


def meets_call_rule(contract: Dict[str, Any], rules: WheelAgentRules) -> bool:
    delta = contract.get("delta")
    return (
        premium_pct(contract) >= rules.min_call_premium_pct
        and delta is not None
        and 0 <= delta <= rules.max_call_delta
    )


def meets_put_rule(contract: Dict[str, Any], rules: WheelAgentRules) -> bool:
    delta = contract.get("delta")
    return (
        premium_pct(contract) >= rules.min_put_premium_pct
        and delta is not None
        and rules.min_put_delta <= delta <= 0
    )


def directional_roll_candidates(
    option: Dict[str, Any],
    candidates: List[Dict[str, Any]],
    equity_position: Optional[Dict[str, Any]],
    rules: WheelAgentRules,
) -> List[Dict[str, Any]]:
    cost_basis = equity_position.get("average_price") if equity_position else None
    current_strike = option.get("strike_price")
    if cost_basis is None or current_strike is None:
        return []

    close_cost = abs(option.get("market_value") or 0)
    quantity = option.get("quantity") or 1
    rows: List[Dict[str, Any]] = []
    for candidate in candidates:
        strike = candidate.get("strike_price")
        bid = candidate.get("bid") or 0
        if strike is None:
            continue
        moves_toward_basis = abs(strike - cost_basis) < abs(current_strike - cost_basis)
        new_credit = bid * CONTRACT_MULTIPLIER * quantity
        if moves_toward_basis and new_credit >= close_cost:
            rows.append(candidate)
    return rows


def recommendation_row(
    action: str,
    symbol: str,
    contract: Dict[str, Any],
    underlying_price: Optional[float],
    max_contracts: int,
    reason: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    row = {
        "action": action,
        "underlying": symbol,
        "underlying_price": rounded(underlying_price),
        "contract": contract_summary(contract),
        "max_contracts": max_contracts,
        "premium_pct_of_strike": rounded(premium_pct(contract), 4),
        "reason": reason,
    }
    if extra:
        row.update(extra)
    return row


def roll_row(
    option: Dict[str, Any],
    candidate: Dict[str, Any],
    underlying_price: Optional[float],
    reason: str,
) -> Dict[str, Any]:
    return {
        "action": "ROLL_SHORT_OPTION",
        "underlying": option.get("underlying"),
        "underlying_price": rounded(underlying_price),
        "current_option": option,
        "roll_to": contract_summary(candidate),
        "premium_pct_of_strike": rounded(premium_pct(candidate), 4),
        "reason": reason,
    }


def contract_summary(contract: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "symbol": contract.get("symbol"),
        "put_call": contract.get("put_call"),
        "strike_price": contract.get("strike_price"),
        "expiration_date": contract.get("expiration_date"),
        "days_to_expiration": contract.get("days_to_expiration"),
        "bid": contract.get("bid"),
        "ask": contract.get("ask"),
        "mark": contract.get("mark"),
        "delta": contract.get("delta"),
        "in_the_money": contract.get("in_the_money"),
        "open_interest": contract.get("open_interest"),
        "volume": contract.get("volume"),
    }

def premium_pct(contract: Dict[str, Any]) -> float:
    strike = contract.get("strike_price") or 0
    premium = contract.get("bid")
    if premium is None:
        premium = contract.get("mark") or 0
    if strike == 0:
        return 0.0
    return premium / strike


def is_short_option_itm(
    option: Dict[str, Any], underlying_price: Optional[float]
) -> bool:
    if underlying_price is None or option.get("strike_price") is None:
        return False
    if option.get("put_call") == "CALL":
        return underlying_price > option["strike_price"]
    if option.get("put_call") == "PUT":
        return underlying_price < option["strike_price"]
    return False


def position_underlying_symbol(position: Position) -> Optional[str]:
    instrument = position.instrument
    if instrument is None:
        return None
    if instrument.underlying_symbol:
        return instrument.underlying_symbol.upper()
    return normalize_trade_symbol(instrument.symbol, instrument.asset_type)


def normalize_trade_symbol(
    symbol: Optional[str], asset_type: Optional[str]
) -> Optional[str]:
    if not symbol or symbol == "CURRENCY_USD":
        return None
    if asset_type == "OPTION":
        return option_symbol_underlying(symbol)
    return symbol.upper()


def option_symbol_underlying(symbol: str) -> Optional[str]:
    stripped = symbol.strip()
    if " " in stripped:
        return stripped.split()[0].upper()
    return None


def rounded(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(value, digits)
