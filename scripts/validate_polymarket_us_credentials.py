from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from polymarket_copy_trading.polymarket_us_api import PolymarketUSClient, PolymarketUSConfigError  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate Polymarket US API credentials without placing trades.")
    parser.add_argument("--env-file", default=".env", help="Optional .env file to load before reading credentials.")
    parser.add_argument("--skip-auth-call", action="store_true", help="Only validate key parsing and signing locally.")
    parser.add_argument("--market-slug", help="Optional Polymarket US market slug to validate public gateway access.")
    parser.add_argument("--json", action="store_true", dest="json_output")
    args = parser.parse_args(argv)

    _load_env(Path(args.env_file))
    report: dict[str, Any] = {
        "configured": False,
        "signature_ok": False,
        "account_balances_ok": False,
        "gateway_ok": False,
        "errors": [],
    }
    try:
        client = PolymarketUSClient.from_env()
        headers = client.auth_headers("GET", "/v1/account/balances", timestamp_ms=1_777_777_777_000)
        report["configured"] = True
        report["signature_ok"] = bool(headers.get("X-PM-Signature"))
    except (PolymarketUSConfigError, ValueError) as exc:
        report["errors"].append(str(exc))
        _print_report(report, json_output=args.json_output)
        return 2

    if not args.skip_auth_call:
        try:
            balances = client.get_account_balances()
            report["account_balances_ok"] = True
            report["account_balance_keys"] = sorted(str(key) for key in balances.keys())
        except Exception as exc:  # pragma: no cover - network/API dependent smoke test
            report["errors"].append(f"account_balances_failed: {exc}")

    if args.market_slug:
        try:
            market = client.get_market_by_slug(args.market_slug)
            report["gateway_ok"] = True
            report["market_slug"] = args.market_slug
            report["market_keys"] = sorted(str(key) for key in market.keys())
        except Exception as exc:  # pragma: no cover - network/API dependent smoke test
            report["errors"].append(f"gateway_market_failed: {exc}")

    _print_report(report, json_output=args.json_output)
    return 0 if report["signature_ok"] and (args.skip_auth_call or report["account_balances_ok"]) else 1


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _print_report(report: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
        return
    print(f"configured={report['configured']}")
    print(f"signature_ok={report['signature_ok']}")
    print(f"account_balances_ok={report['account_balances_ok']}")
    print(f"gateway_ok={report['gateway_ok']}")
    for error in report["errors"]:
        print(f"error={error}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
