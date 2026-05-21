from __future__ import annotations

import time
from datetime import date, datetime, time as datetime_time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional

import requests

from .auth import SchwabAuth
from .config import SchwabConfig
from .models import Account, AccountNumber, OptionChain, Order, Transaction


class SchwabClient:
    def __init__(
        self,
        config: SchwabConfig,
        auth: SchwabAuth,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.config = config
        self.auth = auth
        self.session = session or requests.Session()

    def list_accounts(self) -> List[AccountNumber]:
        payload = self._get("/accounts/accountNumbers")
        return [AccountNumber.model_validate(item) for item in payload]

    def get_positions(self, account_hashes: Optional[Iterable[str]] = None) -> List[Account]:
        return self.get_accounts(fields=("positions",), account_hashes=account_hashes)

    def get_accounts(
        self,
        fields: Iterable[str],
        account_hashes: Optional[Iterable[str]] = None,
    ) -> List[Account]:
        hashes = list(account_hashes or [account.hash_value for account in self.list_accounts()])
        accounts: List[Account] = []
        fields_param = ",".join(fields)
        for account_hash in hashes:
            payload = self._get(f"/accounts/{account_hash}", params={"fields": fields_param})
            accounts.append(Account.model_validate(payload))
        return accounts

    def get_positions_and_balances(
        self, account_hashes: Optional[Iterable[str]] = None
    ) -> List[Account]:
        return self.get_positions(account_hashes=account_hashes)

    def get_open_orders(
        self,
        account_hashes: Optional[Iterable[str]] = None,
        lookback_days: int = 30,
    ) -> List[Order]:
        hashes = list(account_hashes or [account.hash_value for account in self.list_accounts()])
        orders: List[Order] = []
        for account_hash in hashes:
            for status in ("WORKING", "QUEUED", "AWAITING_PARENT_ORDER"):
                payload = self._get(
                    f"/accounts/{account_hash}/orders",
                    params={
                        "fromEnteredTime": self._iso_utc(
                            datetime.now(timezone.utc) - timedelta(days=lookback_days)
                        ),
                        "toEnteredTime": self._iso_utc(datetime.now(timezone.utc)),
                        "maxResults": 3000,
                        "status": status,
                    },
                )
                orders.extend(Order.from_payload(item) for item in payload)
        return orders

    def get_transactions(
        self,
        start_date: date,
        end_date: date,
        account_hashes: Optional[Iterable[str]] = None,
        transaction_type: str = "TRADE",
    ) -> List[Transaction]:
        hashes = list(account_hashes or [account.hash_value for account in self.list_accounts()])
        transactions: List[Transaction] = []
        for account_hash in hashes:
            for chunk_start, chunk_end in self._date_chunks(start_date, end_date):
                payload = self._get(
                    f"/accounts/{account_hash}/transactions",
                    params={
                        "startDate": self._start_of_day_utc(chunk_start),
                        "endDate": self._end_of_day_utc(chunk_end),
                        "types": transaction_type,
                    },
                )
                transactions.extend(
                    Transaction.from_payload(item) for item in payload
                )
        return transactions

    def get_option_chain(
        self,
        symbol: str,
        from_date: date,
        to_date: date,
        contract_type: str = "ALL",
    ) -> OptionChain:
        payload = self._get_marketdata(
            "/chains",
            params={
                "symbol": symbol.upper(),
                "contractType": contract_type,
                "includeUnderlyingQuote": "true",
                "fromDate": from_date.isoformat(),
                "toDate": to_date.isoformat(),
            },
        )
        return OptionChain.model_validate(payload)

    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        return self._get_url(f"{self.config.trader_base_url}{path}", params=params)

    def _get_marketdata(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> Any:
        return self._get_url(
            f"{self.config.marketdata_base_url}{path}", params=params
        )

    def _get_url(self, url: str, params: Optional[Dict[str, Any]] = None) -> Any:
        tokens = self.auth.valid_tokens()
        response = self._session_get_with_retry(
            url,
            headers={"Authorization": f"{tokens.token_type} {tokens.access_token}"},
            params=params,
        )
        if response.status_code == 401:
            tokens = self.auth.refresh(tokens.refresh_token)
            response = self._session_get_with_retry(
                url,
                headers={"Authorization": f"{tokens.token_type} {tokens.access_token}"},
                params=params,
            )
        response.raise_for_status()
        return response.json()

    def _session_get_with_retry(
        self,
        url: str,
        headers: Dict[str, str],
        params: Optional[Dict[str, Any]],
        attempts: int = 3,
    ) -> requests.Response:
        last_error: Optional[requests.RequestException] = None
        for attempt in range(attempts):
            try:
                return self.session.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=30,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    time.sleep(2 ** attempt)
        raise last_error

    @staticmethod
    def _iso_utc(value: datetime) -> str:
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _start_of_day_utc(value: date) -> str:
        return datetime.combine(value, datetime_time.min, timezone.utc).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _end_of_day_utc(value: date) -> str:
        return (
            datetime.combine(value, datetime_time.max, timezone.utc)
            .replace(microsecond=999000)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )

    @staticmethod
    def _date_chunks(start_date: date, end_date: date, max_days: int = 59):
        if end_date < start_date:
            raise ValueError("end_date must be on or after start_date")
        cursor = start_date
        while cursor <= end_date:
            chunk_end = min(cursor + timedelta(days=max_days), end_date)
            yield cursor, chunk_end
            cursor = chunk_end + timedelta(days=1)
