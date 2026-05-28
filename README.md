# Wheel Desk Schwab Assistant

A small read-only Schwab Individual Trader API assistant.

## Setup

Install the package in editable mode:

```bash
python3 -m pip install -e ".[dev]"
```

Set Schwab app credentials from the developer portal:

```bash
export SCHWAB_CLIENT_ID="your app key"
export SCHWAB_CLIENT_SECRET="your app secret"
export SCHWAB_REDIRECT_URI="https://127.0.0.1/callback"
```

Tokens are stored with the OS keychain via `keyring` when available. If no
keychain backend is available, set `SCHWAB_TOKEN_PASSPHRASE` and tokens will be
stored in an encrypted local file at `~/.schwab-assistant/tokens.enc`.

## Authenticate

Run the local HTTPS callback listener:

```bash
python -m src.app auth-login --open
```

Open the printed URL and approve access. Your browser may warn about the local
self-signed certificate for `127.0.0.1`; continue through it to complete the
localhost callback. As a fallback, you can still paste a raw code or full
redirect URL manually:

```bash
python -m src.app auth-code "PASTE_CODE_OR_FULL_REDIRECT_URL_HERE"
```

## Read-only Commands

```bash
python -m src.app accounts
python -m src.app positions
python -m src.app wheel-summary
python -m src.app wheel-agent
python -m src.app option-chain AAPL
python -m src.app open-orders
```

No order placement code is included.

`wheel-summary` highlights option positions where short premium positions have
kept at least 80% of the original credit and option positions expiring in the
next five calendar days. It also includes month-to-date and year-to-date option
trade P/L using Schwab transaction history, plus current balances for each
linked account.

`option-chain SYMBOL` fetches read-only market-data option chains for expirations
under 45 days out and strikes within 15% of the underlying price.

`wheel-agent` suggests next wheel actions without placing orders. It keeps cash
above a 10% account-value reserve, caps cash-secured put collateral by that
reserve rule, uses previously traded/currently held symbols, and optionally
includes symbols from `wheel_symbols.txt`. By default it looks for covered
calls with delta up to `0.35` and premium at or above `2.5%` of strike, and
cash-secured puts with delta between `-0.25` and `0` and premium at or above
`3%` of strike.

Automation prompt text for the recurring morning run is version-controlled in
`automation/daily-wheel-desk-prompt.md`.
