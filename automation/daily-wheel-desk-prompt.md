Run `./run-wheel-tasks.sh` in the Wheel Desk project every Monday through Friday at 9:00 AM local time.

Summarize the outputs in Markdown exactly as follows.

# Wheel Desk Morning Summary

Date: <today>

## Auth Check
- Status: OK | NOT OK
- If not OK, include the failing step and key error.

## Wheel Summary
- Month to Date: $...
- Year to Date: $...

## Expiring Soon
- SYMBOL
- None

## Profit Targets
- SYMBOL
- None

## Wheel Agent Recommendations

### Cash Guardrails
- Aggregate cash: $...
- Aggregate liquidation value: $...
- Required 10% reserve: $...
- Remaining CSP capacity: $...
- Reserve OK: true|false

### By Account

For each account, show a separate subsection:

#### Account <account_number>
- Cash balance: $...
- Liquidation value: $...
- Required cash reserve: $...
- Remaining CSP capacity: $...
- Reserve OK: true|false

Covered Calls
- ACTION | CONTRACT_SYMBOL | EXPIRATION_DATE | STRIKE | DELTA | PREMIUM % | MAX CONTRACTS
- None

Cash-Secured Puts
- ACTION | CONTRACT_SYMBOL | EXPIRATION_DATE | STRIKE | DELTA | PREMIUM % | CASH REQUIRED | AVAILABLE CASH IN ACCOUNT
- None

Closest Miss Cash-Secured Put
- ACTION | CONTRACT_SYMBOL | EXPIRATION_DATE | STRIKE | DELTA | PREMIUM % | CASH REQUIRED | AVAILABLE CASH IN ACCOUNT | MISS REASONS
- None

Rolls
- ACTION | CURRENT_OPTION_SYMBOL | ROLL_TO_SYMBOL | EXPIRATION_DATE | STRIKE | PREMIUM %
- None

Only show covered calls for the account that actually has shares available. Do not repeat covered call ideas in accounts with no shares.

If there are qualifying cash-secured puts, list them in the Cash-Secured Puts section and show `None` for Closest Miss Cash-Secured Put.

If there are no qualifying cash-secured puts, show `None` for Cash-Secured Puts and list the closest miss instead, including the miss reasons.

If there are multiple candidates in a section, preserve the tool ordering exactly as returned by the JSON.

## Symbols
- SYMBOL
- SYMBOL

If any step fails, state the failing step and the key error.

Read-only only. No orders.
