from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SchwabModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class TokenSet(SchwabModel):
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_at: datetime
    scope: Optional[str] = None
    refresh_token_expires_at: Optional[datetime] = None

    @classmethod
    def from_oauth_response(cls, payload: Dict[str, Any]) -> "TokenSet":
        expires_in = int(payload.get("expires_in", 1800))
        refresh_expires_in = payload.get("refresh_token_expires_in")
        refresh_expires_at = None
        if refresh_expires_in is not None:
            refresh_expires_at = utcnow() + timedelta(seconds=int(refresh_expires_in))

        return cls(
            access_token=payload["access_token"],
            refresh_token=payload["refresh_token"],
            token_type=payload.get("token_type", "Bearer"),
            expires_at=utcnow() + timedelta(seconds=expires_in),
            scope=payload.get("scope"),
            refresh_token_expires_at=refresh_expires_at,
        )

    def access_token_expired(self, skew_seconds: int = 60) -> bool:
        return utcnow() >= self.expires_at - timedelta(seconds=skew_seconds)


class AccountNumber(SchwabModel):
    account_number: str = Field(alias="accountNumber")
    hash_value: str = Field(alias="hashValue")


class Instrument(SchwabModel):
    symbol: Optional[str] = None
    description: Optional[str] = None
    asset_type: Optional[str] = Field(default=None, alias="assetType")
    put_call: Optional[str] = Field(default=None, alias="putCall")
    underlying_symbol: Optional[str] = Field(default=None, alias="underlyingSymbol")
    expiration_date: Optional[str] = Field(default=None, alias="expirationDate")
    strike_price: Optional[float] = Field(default=None, alias="strikePrice")


class Position(SchwabModel):
    short_quantity: Optional[float] = Field(default=None, alias="shortQuantity")
    long_quantity: Optional[float] = Field(default=None, alias="longQuantity")
    average_price: Optional[float] = Field(default=None, alias="averagePrice")
    market_value: Optional[float] = Field(default=None, alias="marketValue")
    instrument: Optional[Instrument] = None


class Balance(SchwabModel):
    cash_balance: Optional[float] = Field(default=None, alias="cashBalance")
    cash_available_for_trading: Optional[float] = Field(
        default=None, alias="cashAvailableForTrading"
    )
    buying_power: Optional[float] = Field(default=None, alias="buyingPower")
    option_buying_power: Optional[float] = Field(default=None, alias="optionBuyingPower")
    liquidation_value: Optional[float] = Field(default=None, alias="liquidationValue")
    long_market_value: Optional[float] = Field(default=None, alias="longMarketValue")
    short_market_value: Optional[float] = Field(default=None, alias="shortMarketValue")
    maintenance_requirement: Optional[float] = Field(
        default=None, alias="maintenanceRequirement"
    )
    maintenance_call: Optional[float] = Field(default=None, alias="maintenanceCall")
    available_funds: Optional[float] = Field(default=None, alias="availableFunds")
    available_funds_non_marginable_trade: Optional[float] = Field(
        default=None, alias="availableFundsNonMarginableTrade"
    )


class SecuritiesAccount(SchwabModel):
    account_number: Optional[str] = Field(default=None, alias="accountNumber")
    type: Optional[str] = None
    positions: List[Position] = Field(default_factory=list)
    current_balances: Optional[Balance] = Field(default=None, alias="currentBalances")
    initial_balances: Optional[Balance] = Field(default=None, alias="initialBalances")
    projected_balances: Optional[Balance] = Field(default=None, alias="projectedBalances")


class Account(SchwabModel):
    securities_account: SecuritiesAccount = Field(alias="securitiesAccount")


class Order(SchwabModel):
    order_id: Optional[int] = Field(default=None, alias="orderId")
    status: Optional[str] = None
    entered_time: Optional[str] = Field(default=None, alias="enteredTime")
    close_time: Optional[str] = Field(default=None, alias="closeTime")
    account_number: Optional[str] = Field(default=None, alias="accountNumber")
    raw: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "Order":
        model = cls.model_validate(payload)
        model.raw = payload
        return model


class TransactionItem(SchwabModel):
    amount: Optional[float] = None
    price: Optional[float] = None
    cost: Optional[float] = None
    instruction: Optional[str] = None
    position_effect: Optional[str] = Field(default=None, alias="positionEffect")
    fee_type: Optional[str] = Field(default=None, alias="feeType")
    instrument: Optional[Instrument] = None


class Transaction(SchwabModel):
    transaction_id: Optional[Union[int, str]] = Field(default=None, alias="transactionId")
    activity_id: Optional[Union[int, str]] = Field(default=None, alias="activityId")
    transaction_date: Optional[str] = Field(default=None, alias="transactionDate")
    trade_date: Optional[str] = Field(default=None, alias="tradeDate")
    time: Optional[str] = None
    settlement_date: Optional[str] = Field(default=None, alias="settlementDate")
    type: Optional[str] = None
    status: Optional[str] = None
    description: Optional[str] = None
    net_amount: Optional[float] = Field(default=None, alias="netAmount")
    transaction_item: Optional[Union[TransactionItem, List[TransactionItem]]] = Field(
        default=None, alias="transactionItem"
    )
    raw: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "Transaction":
        model = cls.model_validate(payload)
        model.raw = payload
        return model

    def items(self) -> List[TransactionItem]:
        if self.transaction_item is None:
            return []
        if isinstance(self.transaction_item, list):
            return self.transaction_item
        return [self.transaction_item]


class OptionContract(SchwabModel):
    put_call: Optional[str] = Field(default=None, alias="putCall")
    symbol: Optional[str] = None
    description: Optional[str] = None
    exchange_name: Optional[str] = Field(default=None, alias="exchangeName")
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    mark: Optional[float] = None
    delta: Optional[float] = None
    theta: Optional[float] = None
    gamma: Optional[float] = None
    vega: Optional[float] = None
    rho: Optional[float] = None
    volatility: Optional[float] = None
    open_interest: Optional[int] = Field(default=None, alias="openInterest")
    total_volume: Optional[int] = Field(default=None, alias="totalVolume")
    strike_price: Optional[float] = Field(default=None, alias="strikePrice")
    expiration_date: Optional[str] = Field(default=None, alias="expirationDate")
    days_to_expiration: Optional[int] = Field(default=None, alias="daysToExpiration")
    in_the_money: Optional[bool] = Field(default=None, alias="inTheMoney")


class OptionChain(SchwabModel):
    symbol: Optional[str] = None
    status: Optional[str] = None
    underlying_price: Optional[float] = Field(default=None, alias="underlyingPrice")
    call_exp_date_map: Dict[str, Dict[str, List[OptionContract]]] = Field(
        default_factory=dict, alias="callExpDateMap"
    )
    put_exp_date_map: Dict[str, Dict[str, List[OptionContract]]] = Field(
        default_factory=dict, alias="putExpDateMap"
    )
    underlying: Dict[str, Any] = Field(default_factory=dict)
