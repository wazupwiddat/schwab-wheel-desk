#!/usr/bin/env bash
set -euo pipefail

cd "/Users/jameswarren/Documents/codex/Wheel Desk"

PYTHONPATH=. .venv/bin/python -m src.app auth-check
PYTHONPATH=. .venv/bin/python -m src.app wheel-summary
PYTHONPATH=. .venv/bin/python -m src.app wheel-agent
