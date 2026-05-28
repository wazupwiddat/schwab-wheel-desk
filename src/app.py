from __future__ import annotations

import argparse
import json
import os
import sys
import webbrowser
from datetime import date
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from .auth import SchwabAuth
from .callback_server import wait_for_oauth_callback
from .client import SchwabClient
from .config import SchwabConfig
from .models import Account, AccountNumber, Order
from .option_chains import option_chain_window, summarize_option_chain
from .token_store import EncryptedFileTokenStore, KeyringTokenStore, build_token_store
from .wheel_agent import (
    WheelAgentRules,
    build_wheel_recommendations,
    load_symbol_file,
)
from .wheel_summary import build_wheel_summary


def build_auth() -> SchwabAuth:
    config = SchwabConfig.from_env()
    return SchwabAuth(
        config=config,
        token_store=build_token_store(config.keyring_service, config.token_path),
    )


def build_client() -> SchwabClient:
    auth = build_auth()
    return SchwabClient(config=auth.config, auth=auth)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Schwab read-only trading assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_url_parser = subparsers.add_parser("auth-url", help="Print OAuth URL")
    auth_url_parser.add_argument("--state", help="Optional OAuth state value")

    login_parser = subparsers.add_parser(
        "auth-login", help="Run a local callback server and store OAuth tokens"
    )
    login_parser.add_argument("--timeout", type=int, default=180)
    login_parser.add_argument("--state", help="Optional OAuth state value")
    login_parser.add_argument(
        "--open", action="store_true", help="Open the Schwab authorization URL"
    )

    auth_code_parser = subparsers.add_parser("auth-code", help="Store tokens from OAuth code")
    auth_code_parser.add_argument("code", help="Authorization code from Schwab redirect")

    subparsers.add_parser(
        "auth-export-file",
        help="Copy keychain tokens to encrypted file storage for automations",
    )
    subparsers.add_parser(
        "auth-check",
        help="Print sanitized Schwab auth/config diagnostics as JSON",
    )

    subparsers.add_parser("accounts", help="List linked account hashes")
    subparsers.add_parser("positions", help="Show positions for linked accounts")

    wheel_parser = subparsers.add_parser(
        "wheel-summary", help="Show wheel option positions needing attention"
    )
    wheel_parser.add_argument("--profit-threshold", type=float, default=0.80)
    wheel_parser.add_argument("--expiry-days", type=int, default=5)

    orders_parser = subparsers.add_parser("open-orders", help="Show open orders")
    orders_parser.add_argument("--lookback-days", type=int, default=30)

    chain_parser = subparsers.add_parser(
        "option-chain", help="Fetch a filtered option chain for a symbol"
    )
    chain_parser.add_argument("symbol", help="Underlying ticker symbol")
    chain_parser.add_argument("--max-days", type=int, default=44)
    chain_parser.add_argument("--strike-pct", type=float, default=0.15)

    agent_parser = subparsers.add_parser(
        "wheel-agent", help="Suggest next wheel strategy actions"
    )
    agent_parser.add_argument("--symbols-file", default="wheel_symbols.txt")
    agent_parser.add_argument("--symbols", help="Comma-separated symbols to include")
    agent_parser.add_argument("--reserve-cash-pct", type=float, default=0.10)
    agent_parser.add_argument("--min-call-premium-pct", type=float, default=0.025)
    agent_parser.add_argument("--min-put-premium-pct", type=float, default=0.03)
    agent_parser.add_argument("--max-call-delta", type=float, default=0.35)
    agent_parser.add_argument("--min-put-delta", type=float, default=-0.25)
    agent_parser.add_argument("--max-dte", type=int, default=31)
    agent_parser.add_argument("--min-roll-premium-pct", type=float, default=0.02)

    args = parser.parse_args(argv)

    try:
        if args.command == "auth-url":
            auth = build_auth()
            print(auth.authorization_url(state=args.state))
            return 0
        if args.command == "auth-login":
            auth = build_auth()
            authorization_url = auth.authorization_url(state=args.state)
            print("Open this Schwab authorization URL:")
            print(authorization_url)
            print()
            if args.open:
                webbrowser.open(authorization_url)
            print(
                "Waiting for callback on "
                f"{auth.config.redirect_uri} for up to {args.timeout} seconds..."
            )
            callback = wait_for_oauth_callback(
                auth.config.redirect_uri, timeout_seconds=args.timeout
            )
            auth.exchange_code(callback.code)
            print("Schwab tokens stored.")
            return 0
        if args.command == "auth-code":
            auth = build_auth()
            auth.exchange_code(extract_authorization_code(args.code))
            print("Schwab tokens stored.")
            return 0
        if args.command == "auth-export-file":
            config = SchwabConfig.from_env()
            passphrase = os.getenv("SCHWAB_TOKEN_PASSPHRASE")
            if not passphrase:
                raise RuntimeError(
                    "Set SCHWAB_TOKEN_PASSPHRASE before running auth-export-file."
                )
            source = KeyringTokenStore(service=config.keyring_service)
            tokens = source.load()
            if tokens is None:
                raise RuntimeError("No Schwab tokens found in keyring.")
            EncryptedFileTokenStore(config.token_path, passphrase).save(tokens)
            print(f"Schwab tokens exported to encrypted file: {config.token_path}")
            return 0
        if args.command == "auth-check":
            print_json(auth_check())
            return 0
        if args.command == "accounts":
            accounts = build_client().list_accounts()
            print_json([_dump(account) for account in accounts])
            return 0
        if args.command == "positions":
            accounts = build_client().get_positions()
            print_positions(accounts)
            return 0
        if args.command == "wheel-summary":
            client = build_client()
            accounts = client.get_positions_and_balances()
            as_of = date.today()
            transactions = client.get_transactions(
                start_date=as_of.replace(month=1, day=1),
                end_date=as_of,
            )
            summary = build_wheel_summary(
                accounts,
                transactions=transactions,
                as_of=as_of,
                profit_threshold=args.profit_threshold,
                expiry_days=args.expiry_days,
            )
            print_json(summary.to_dict())
            return 0
        if args.command == "open-orders":
            orders = build_client().get_open_orders(lookback_days=args.lookback_days)
            print_json([_dump(order) for order in orders])
            return 0
        if args.command == "option-chain":
            as_of = date.today()
            from_date, to_date = option_chain_window(as_of, max_days=args.max_days)
            chain = build_client().get_option_chain(
                args.symbol,
                from_date=from_date,
                to_date=to_date,
            )
            print_json(
                summarize_option_chain(
                    chain,
                    as_of=as_of,
                    max_days=args.max_days,
                    strike_pct=args.strike_pct,
                )
            )
            return 0
        if args.command == "wheel-agent":
            print_json(run_wheel_agent(args))
            return 0
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1


def print_positions(accounts: list[Account]) -> None:
    rows: list[dict[str, Any]] = []
    for account in accounts:
        securities_account = account.securities_account
        for position in securities_account.positions:
            instrument = position.instrument
            rows.append(
                {
                    "account": securities_account.account_number,
                    "symbol": instrument.symbol if instrument else None,
                    "asset_type": instrument.asset_type if instrument else None,
                    "long_quantity": position.long_quantity,
                    "short_quantity": position.short_quantity,
                    "average_price": position.average_price,
                    "market_value": position.market_value,
                }
            )
    print_json(rows)


def print_json(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True, default=str))


def _dump(value: AccountNumber | Order) -> dict[str, Any]:
    return value.model_dump(mode="json", by_alias=True)


def extract_authorization_code(value: str) -> str:
    parsed = urlparse(value)
    if parsed.query:
        code = parse_qs(parsed.query).get("code")
        if code:
            return code[0]
    return value


def load_agent_symbols(symbols_file: str, symbols: Optional[str]) -> list[str]:
    loaded = load_symbol_file(Path(symbols_file))
    if symbols:
        loaded.extend(symbol.strip().upper() for symbol in symbols.split(",") if symbol.strip())
    return loaded


def auth_check() -> dict[str, Any]:
    try:
        config = SchwabConfig.from_env()
    except Exception as exc:
        return {
            "status": "blocked",
            "error": str(exc),
            "cwd": str(Path.cwd()),
            "env_file": os.getenv("SCHWAB_ENV_FILE"),
        }

    token_store = build_token_store(config.keyring_service, config.token_path)
    token_available = False
    token_error = None
    try:
        token_available = token_store.load() is not None
    except Exception as exc:
        token_error = str(exc)

    return {
        "status": "ok" if token_available else "blocked",
        "cwd": str(Path.cwd()),
        "env_file": os.getenv("SCHWAB_ENV_FILE"),
        "token_store": os.getenv("SCHWAB_TOKEN_STORE", "auto"),
        "token_path": str(config.token_path),
        "token_path_exists": config.token_path.exists(),
        "token_available": token_available,
        "token_error": token_error,
        "auth_base_url": config.auth_base_url,
        "trader_base_url": config.trader_base_url,
        "marketdata_base_url": config.marketdata_base_url,
        "redirect_uri_host": urlparse(config.redirect_uri).hostname,
        "client_id_suffix": config.client_id[-6:],
    }


def run_wheel_agent(args: Any) -> dict[str, Any]:
    as_of = date.today()
    rules = WheelAgentRules(
        reserve_cash_pct=args.reserve_cash_pct,
        min_call_premium_pct=args.min_call_premium_pct,
        min_put_premium_pct=args.min_put_premium_pct,
        max_call_delta=args.max_call_delta,
        min_put_delta=args.min_put_delta,
        max_dte=args.max_dte,
        min_roll_premium_pct=args.min_roll_premium_pct,
    )
    stored_symbols = load_agent_symbols(args.symbols_file, args.symbols)

    try:
        client = build_client()
        accounts = client.get_positions_and_balances()
        transactions = client.get_transactions(
            start_date=as_of.replace(month=1, day=1),
            end_date=as_of,
        )
    except Exception as exc:
        return wheel_agent_blocked_payload(
            as_of=as_of,
            rules=rules,
            stored_symbols=stored_symbols,
            error=exc,
            stage="account_or_transaction_lookup",
        )

    provisional = build_wheel_recommendations(
        accounts=accounts,
        transactions=transactions,
        option_chains={},
        stored_symbols=stored_symbols,
        as_of=as_of,
        rules=rules,
    )
    option_chains = {}
    warnings = []
    from_date, to_date = option_chain_window(as_of, max_days=rules.max_dte)
    for symbol in provisional["symbols"]:
        try:
            option_chains[symbol] = client.get_option_chain(
                symbol, from_date=from_date, to_date=to_date
            )
        except Exception as exc:
            warnings.append(f"Unable to fetch option chain for {symbol}: {exc}")

    recommendations = build_wheel_recommendations(
        accounts=accounts,
        transactions=transactions,
        option_chains=option_chains,
        stored_symbols=stored_symbols,
        as_of=as_of,
        rules=rules,
    )
    if warnings:
        recommendations["warnings"] = warnings
    return recommendations


def wheel_agent_blocked_payload(
    as_of: date,
    rules: WheelAgentRules,
    stored_symbols: list[str],
    error: Exception,
    stage: str,
) -> dict[str, Any]:
    return {
        "as_of": as_of.isoformat(),
        "status": "blocked",
        "blocked_stage": stage,
        "error": str(error),
        "cash_guardrails": {
            "accounts": [],
            "aggregate": {
                "cash_balance": None,
                "liquidation_value": None,
                "required_cash_reserve": None,
                "open_cash_secured_put_collateral": None,
                "remaining_csp_capacity": None,
                "reserve_ok": None,
            },
        },
        "recommendations": {
            "rolls": [],
            "covered_calls": [],
            "cash_secured_puts": [],
            "cash_secured_put_closest_miss": None,
            "by_account": [],
        },
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
        "symbols": sorted(set(stored_symbols)),
        "warnings": [
            "Schwab data was unavailable, so no recommendations were generated.",
            "No trades were placed.",
        ],
        "notes": [
            "Read-only suggestions only; no orders are placed.",
            "This JSON payload is intentionally returned even when Schwab is unreachable.",
        ],
    }


if __name__ == "__main__":
    raise SystemExit(main())
