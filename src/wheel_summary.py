from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from .models import Account, Balance, Position, Transaction, TransactionItem


OPTION_MULTIPLIER = 100
OSI_EXPIRATION_RE = re.compile(r"\s(\d{6})[CP]\d{8}$")


@dataclass(frozen=True)
class WheelSummary:
    profit_targets: List[Dict[str, Any]]
    expiring_soon: List[Dict[str, Any]]
    profit_loss: Dict[str, Any]
    balances: List[Dict[str, Any]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "profit_targets": self.profit_targets,
            "expiring_soon": self.expiring_soon,
            "profit_loss": self.profit_loss,
            "balances": self.balances,
        }


def build_wheel_summary(
    accounts: List[Account],
    transactions: Optional[List[Transaction]] = None,
    as_of: Optional[date] = None,
    profit_threshold: float = 0.80,
    expiry_days: int = 5,
) -> WheelSummary:
    as_of = as_of or date.today()
    profit_targets: List[Dict[str, Any]] = []
    expiring_soon: List[Dict[str, Any]] = []

    for account in accounts:
        account_number = account.securities_account.account_number
        for position in account.securities_account.positions:
            if not is_option_position(position):
                continue

            row = option_position_row(account_number, position, as_of)
            profit_percent = row.get("profit_percent")
            days_to_expiration = row.get("days_to_expiration")

            if profit_percent is not None and profit_percent >= profit_threshold:
                profit_targets.append(row)
            if days_to_expiration is not None and 0 <= days_to_expiration <= expiry_days:
                expiring_soon.append(row)

    return WheelSummary(
        profit_targets=sorted(
            profit_targets,
            key=lambda row: (
                row.get("profit_percent") is None,
                -(row.get("profit_percent") or 0),
                row.get("symbol") or "",
            ),
        ),
        expiring_soon=sorted(
            expiring_soon,
            key=lambda row: (
                row.get("days_to_expiration") is None,
                row.get("days_to_expiration") or 999999,
                row.get("symbol") or "",
            ),
        ),
        profit_loss=build_option_profit_loss(transactions or [], as_of),
        balances=build_account_balances(accounts),
    )


def build_account_balances(accounts: List[Account]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for account in accounts:
        securities_account = account.securities_account
        balances = securities_account.current_balances
        if balances is None:
            balances = securities_account.projected_balances
        if balances is None:
            balances = securities_account.initial_balances
        if balances is None:
            rows.append(
                {
                    "account": securities_account.account_number,
                    "account_type": securities_account.type,
                    "available": False,
                }
            )
            continue

        rows.append(
            {
                "account": securities_account.account_number,
                "account_type": securities_account.type,
                "available": True,
                "cash_balance": rounded(balances.cash_balance),
                "cash_available_for_trading": rounded(
                    balances.cash_available_for_trading
                ),
                "buying_power": rounded(balances.buying_power),
                "option_buying_power": rounded(balances.option_buying_power),
                "liquidation_value": rounded(balances.liquidation_value),
                "long_market_value": rounded(balances.long_market_value),
                "short_market_value": rounded(balances.short_market_value),
                "maintenance_requirement": rounded(
                    balances.maintenance_requirement
                ),
                "maintenance_call": rounded(balances.maintenance_call),
                "available_funds": rounded(balances.available_funds),
                "available_funds_non_marginable_trade": rounded(
                    balances.available_funds_non_marginable_trade
                ),
            }
        )
    return rows


def rounded(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, 2)


def is_option_position(position: Position) -> bool:
    instrument = position.instrument
    return bool(instrument and instrument.asset_type == "OPTION")


def option_position_row(
    account_number: Optional[str], position: Position, as_of: date
) -> Dict[str, Any]:
    instrument = position.instrument
    expiration = parse_expiration_date(
        instrument.expiration_date if instrument else None,
        instrument.symbol if instrument else None,
    )
    cost_basis = option_cost_basis(position)
    current_value = abs(position.market_value) if position.market_value is not None else None
    profit_percent = option_profit_percent(position, cost_basis, current_value)

    return {
        "account": account_number,
        "symbol": instrument.symbol if instrument else None,
        "underlying": instrument.underlying_symbol if instrument else None,
        "put_call": instrument.put_call if instrument else None,
        "strike_price": instrument.strike_price if instrument else None,
        "expiration_date": expiration.isoformat() if expiration else None,
        "days_to_expiration": (expiration - as_of).days if expiration else None,
        "quantity": option_quantity(position),
        "side": option_side(position),
        "average_price": position.average_price,
        "cost_basis": round(cost_basis, 2) if cost_basis is not None else None,
        "market_value": position.market_value,
        "current_value": round(current_value, 2) if current_value is not None else None,
        "profit_percent": round(profit_percent, 4) if profit_percent is not None else None,
    }


def option_quantity(position: Position) -> Optional[float]:
    if position.short_quantity:
        return position.short_quantity
    if position.long_quantity:
        return position.long_quantity
    return None


def build_option_profit_loss(
    transactions: List[Transaction], as_of: date
) -> Dict[str, Any]:
    month_start = as_of.replace(day=1)
    year_start = as_of.replace(month=1, day=1)

    month_total = 0.0
    year_total = 0.0
    month_count = 0
    year_count = 0

    for transaction in transactions:
        if not is_option_transaction(transaction):
            continue
        transaction_date = parse_transaction_date(transaction)
        if transaction_date is None or transaction.net_amount is None:
            continue
        if year_start <= transaction_date <= as_of:
            year_total += transaction.net_amount
            year_count += 1
        if month_start <= transaction_date <= as_of:
            month_total += transaction.net_amount
            month_count += 1

    return {
        "month_to_date": round(month_total, 2),
        "year_to_date": round(year_total, 2),
        "month_to_date_transaction_count": month_count,
        "year_to_date_transaction_count": year_count,
        "basis": "Sum of option TRADE transaction netAmount values.",
    }


def is_option_transaction(transaction: Transaction) -> bool:
    return any(is_option_transaction_item(item) for item in transaction_items(transaction))


def transaction_items(transaction: Transaction) -> List[TransactionItem]:
    items = transaction.items()
    if items:
        return items

    raw_items = transaction.raw.get("transactionItems")
    if raw_items is None:
        raw_items = transaction.raw.get("transferItems")
    if raw_items is None:
        return []
    if isinstance(raw_items, dict):
        raw_items = [raw_items]
    return [TransactionItem.model_validate(item) for item in raw_items]


def is_option_transaction_item(item: TransactionItem) -> bool:
    instrument = item.instrument
    if instrument is None:
        return False
    if instrument.asset_type == "OPTION":
        return True
    return parse_expiration_date(instrument.expiration_date, instrument.symbol) is not None


def parse_transaction_date(transaction: Transaction) -> Optional[date]:
    raw = (
        transaction.transaction_date
        or transaction.time
        or transaction.trade_date
        or transaction.settlement_date
    )
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        except ValueError:
            return None


def option_side(position: Position) -> Optional[str]:
    if position.short_quantity:
        return "SHORT"
    if position.long_quantity:
        return "LONG"
    return None


def option_cost_basis(position: Position) -> Optional[float]:
    quantity = option_quantity(position)
    if quantity is None or position.average_price is None:
        return None
    return abs(quantity) * abs(position.average_price) * OPTION_MULTIPLIER


def option_profit_percent(
    position: Position,
    cost_basis: Optional[float],
    current_value: Optional[float],
) -> Optional[float]:
    if cost_basis is None or current_value is None or cost_basis == 0:
        return None
    if position.short_quantity:
        return 1 - (current_value / cost_basis)
    if position.long_quantity:
        return (current_value / cost_basis) - 1
    return None


def parse_expiration_date(
    expiration_date: Optional[str], symbol: Optional[str]
) -> Optional[date]:
    if expiration_date:
        for candidate in (expiration_date, expiration_date[:10]):
            try:
                return datetime.fromisoformat(candidate.replace("Z", "+00:00")).date()
            except ValueError:
                pass

    if symbol:
        match = OSI_EXPIRATION_RE.search(symbol)
        if match:
            raw = match.group(1)
            return datetime.strptime(raw, "%y%m%d").date()

    return None
