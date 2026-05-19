from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from polymarket_copy_trading.config import AppSettings, load_config
from polymarket_copy_trading.dashboard import create_app
from polymarket_copy_trading.execution_service import (
    ExecutionReceiptStore,
    ExecutionServiceClient,
    RemoteExecutionBroker,
    create_execution_app,
)
from polymarket_copy_trading.engine import CopyTradingEngine
from polymarket_copy_trading.live_executor import (
    LivePolymarketBroker,
    post_planned_live_order_intents,
    reconcile_live_order_intents,
    redeem_planned_settlement_intents,
)
from polymarket_copy_trading.live_watcher import LivePaperWatcher
from polymarket_copy_trading.market_data import MarketDataClient
from polymarket_copy_trading.price_monitor import PriceMonitor
from polymarket_copy_trading.store import Store
from polymarket_copy_trading.watcher import load_fixture_trades


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="polymarket-copy-trading")
    parser.add_argument("--config", default=os.environ.get("CONFIG_PATH", "config.yaml"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db")
    init_db.add_argument("--config", dest="command_config")

    maintain_db = subparsers.add_parser("maintain-db")
    maintain_db.add_argument("--config", dest="command_config")
    maintain_db.add_argument("--retention-hours", type=int, default=72)
    maintain_db.add_argument("--apply", action="store_true")
    maintain_db.add_argument("--vacuum", action="store_true")
    maintain_db.add_argument("--analyze", action="store_true")
    maintain_db.add_argument("--json", action="store_true", dest="json_output")

    run_once = subparsers.add_parser("run-once")
    run_once.add_argument("--config", dest="command_config")
    run_once.add_argument("--fixture", default="fixtures/source_trades.json")

    dashboard = subparsers.add_parser("run-dashboard")
    dashboard.add_argument("--config", dest="command_config")
    dashboard.add_argument("--host")
    dashboard.add_argument("--port", type=int)

    trader = subparsers.add_parser("run-paper-trader")
    trader.add_argument("--config", dest="command_config")
    trader.add_argument("--poll-seconds", type=float, default=2.0)

    price_monitor = subparsers.add_parser("run-price-monitor")
    price_monitor.add_argument("--config", dest="command_config")
    price_monitor.add_argument("--poll-seconds", type=float)
    price_monitor.add_argument("--once", action="store_true")

    live_settlements = subparsers.add_parser("run-live-settlements")
    live_settlements.add_argument("--config", dest="command_config")
    live_settlements.add_argument("--limit", type=int, default=50)
    live_settlements.add_argument("--execution-service-url")

    live_orders = subparsers.add_parser("run-live-orders")
    live_orders.add_argument("--config", dest="command_config")
    live_orders.add_argument("--limit", type=int, default=50)
    live_orders.add_argument("--tick-size", default="auto")
    live_orders.add_argument("--execution-service-url")

    live_order_reconciliation = subparsers.add_parser("run-live-order-reconciliation")
    live_order_reconciliation.add_argument("--config", dest="command_config")
    live_order_reconciliation.add_argument("--limit", type=int, default=100)
    live_order_reconciliation.add_argument("--execution-service-url", required=True)

    execution_service = subparsers.add_parser("run-execution-service")
    execution_service.add_argument("--config", dest="command_config")
    execution_service.add_argument("--host", default=os.environ.get("EXECUTION_GATEWAY_HOST", "127.0.0.1"))
    execution_service.add_argument("--port", type=int, default=int(os.environ.get("EXECUTION_GATEWAY_PORT", "8791")))
    execution_service.add_argument(
        "--receipt-db",
        default=os.environ.get("EXECUTION_GATEWAY_RECEIPT_DB", "data/execution_gateway_receipts.sqlite3"),
    )
    execution_service.add_argument(
        "--execution-enabled",
        action="store_true",
        default=_env_bool("EXECUTION_GATEWAY_EXECUTION_ENABLED", default=False),
    )

    derive_api_key = subparsers.add_parser("derive-polymarket-api-key")
    derive_api_key.add_argument("--config", dest="command_config")
    derive_api_key.add_argument("--nonce", type=int)

    args = parser.parse_args(argv)
    load_env_file(PROJECT_ROOT / ".env")
    config_path = args.command_config or args.config
    config = load_config(PROJECT_ROOT / config_path)
    store = build_store(config)
    store.initialize()
    prepare_runtime_store(config, store)

    if args.command == "init-db":
        print(f"Initialized database at {store.path}")
        return 0
    if args.command == "maintain-db":
        before = store.database_maintenance_report(retention_hours=args.retention_hours)
        prune = store.prune_old_source_history(
            retention_hours=args.retention_hours,
            apply=args.apply,
            vacuum=args.vacuum,
            analyze=args.analyze,
        )
        optimize = store.optimize_database(analyze=False) if not args.analyze else {"analyzed": True}
        after = store.database_maintenance_report(retention_hours=args.retention_hours) if args.apply else None
        payload = {"before": before, "prune": prune, "optimize": optimize, "after": after}
        if args.json_output:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_maintenance_summary(payload)
        return 0
    if args.command == "run-once":
        engine = CopyTradingEngine(config=config, store=store)
        stats = engine.process_trades(load_fixture_trades(PROJECT_ROOT / args.fixture))
        print(
            "Processed fixture trades: "
            f"processed={stats['processed']} ignored={stats['ignored']} "
            f"duplicates={stats['duplicates']} skipped={stats['skipped']} attributed={stats['attributed']}"
        )
        return 0
    if args.command == "run-dashboard":
        app = create_app(store=store, config=config, config_path=PROJECT_ROOT / config_path)
        app.run(host=args.host or config.app.host, port=args.port or config.app.port)
        return 0
    if args.command == "run-paper-trader":
        market_data = MarketDataClient()
        LivePaperWatcher(
            config=config,
            store=store,
            buy_price_resolver=market_data.best_effort_buy_price,
            market_metadata_resolver=market_data.market_metadata,
            source_position_resolver=market_data.source_position_snapshot,
            config_reloader=lambda: load_config(PROJECT_ROOT / config_path),
        ).run_forever(poll_seconds=args.poll_seconds)
        return 0
    if args.command == "run-price-monitor":
        monitor = PriceMonitor(config=config, store=store, config_path=PROJECT_ROOT / config_path)
        if args.once:
            stats = monitor.refresh_once()
            print(
                "Refreshed prices: "
                f"priced={stats['priced']} metadata={stats['metadata']} errors={stats['errors']}"
            )
            return 0
        monitor.run_forever(poll_seconds=args.poll_seconds)
        return 0
    if args.command == "run-live-settlements":
        if not _require_live_mode(config, args.command):
            return 2
        broker = (
            RemoteExecutionBroker(
                client=ExecutionServiceClient(
                    base_url=args.execution_service_url,
                    auth_secret=os.environ.get("EXECUTION_GATEWAY_AUTH_SECRET"),
                )
            )
            if args.execution_service_url
            else LivePolymarketBroker.from_env()
        )
        stats = redeem_planned_settlement_intents(
            store=store,
            broker=broker,
            limit=args.limit,
        )
        print(
            "Redeemed live settlement intents: "
            f"planned={stats['planned']} redeemed={stats['redeemed']} errors={stats['errors']}"
        )
        return 0
    if args.command == "run-live-orders":
        if not _require_live_mode(config, args.command):
            return 2
        broker = (
            RemoteExecutionBroker(
                client=ExecutionServiceClient(
                    base_url=args.execution_service_url,
                    auth_secret=os.environ.get("EXECUTION_GATEWAY_AUTH_SECRET"),
                )
            )
            if args.execution_service_url
            else LivePolymarketBroker.from_env()
        )
        stats = post_planned_live_order_intents(
            store=store,
            broker=broker,
            limit=args.limit,
            tick_size=args.tick_size,
        )
        print(
            "Posted live order intents: "
            f"planned={stats['planned']} posted={stats['posted']} "
            f"rejected={stats['rejected']} errors={stats['errors']}"
        )
        return 0
    if args.command == "run-live-order-reconciliation":
        if not _require_live_mode(config, args.command):
            return 2
        broker = RemoteExecutionBroker(
            client=ExecutionServiceClient(
                base_url=args.execution_service_url,
                auth_secret=os.environ.get("EXECUTION_GATEWAY_AUTH_SECRET"),
            )
        )
        stats = reconcile_live_order_intents(store=store, broker=broker, limit=args.limit)
        print(
            "Reconciled live order intents: "
            f"open={stats['open']} updated={stats['updated']} errors={stats['errors']}"
        )
        return 0
    if args.command == "derive-polymarket-api-key":
        if not _require_live_mode(config, args.command):
            return 2
        print(
            "derive-polymarket-api-key is deprecated for Polymarket US. "
            "Create POLYMARKET_US_KEY_ID and POLYMARKET_US_SECRET_KEY in the developer portal, then run "
            "python scripts/validate_polymarket_us_credentials.py --env-file .env --json"
        )
        return 2
    if args.command == "run-execution-service":
        if not _require_live_mode(config, args.command):
            return 2
        auth_secret = os.environ.get("EXECUTION_GATEWAY_AUTH_SECRET")
        if not auth_secret:
            print("run-execution-service requires EXECUTION_GATEWAY_AUTH_SECRET")
            return 2
        receipt_path = Path(args.receipt_db)
        if not receipt_path.is_absolute():
            receipt_path = PROJECT_ROOT / receipt_path
        app = create_execution_app(
            broker=LivePolymarketBroker.from_env(),
            auth_secret=auth_secret,
            receipt_store=ExecutionReceiptStore(receipt_path),
            execution_enabled=bool(args.execution_enabled),
        )
        app.run(host=args.host, port=args.port)
        return 0
    return 2


def build_store(config: AppSettings, *, project_root: Path = PROJECT_ROOT) -> Store:
    database_url = database_url_for_mode(config)
    return Store(database_path_from_url(database_url, project_root=project_root))


def prepare_runtime_store(config: AppSettings, store: Store, *, project_root: Path = PROJECT_ROOT) -> None:
    if config.mode.trading_mode == "live":
        paper_path = database_path_from_url(paper_database_url(config), project_root=project_root)
        if paper_path.exists() and paper_path.resolve() != store.path.resolve():
            paper_store = Store(paper_path)
            paper_store.initialize()
            store.import_wallets_if_empty(paper_store)
    store.seed_wallets_if_empty(config.wallets)


def database_url_for_mode(config: AppSettings) -> str:
    if config.mode.trading_mode == "live":
        return os.environ.get("LIVE_DATABASE_URL") or config.app.live_database_url
    return paper_database_url(config)


def paper_database_url(config: AppSettings) -> str:
    return os.environ.get("DATABASE_URL", config.app.database_url)


def _require_live_mode(config: AppSettings, command: str) -> bool:
    if config.mode.trading_mode == "live":
        return True
    print(f"{command} is disabled unless mode.trading_mode is live")
    return False


def _env_bool(key: str, *, default: bool = False) -> bool:
    value = os.environ.get(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "enabled"}


def database_path_from_url(database_url: str, *, project_root: Path = PROJECT_ROOT) -> Path:
    prefix = "sqlite:///"
    if not database_url.startswith(prefix):
        raise ValueError("only sqlite:/// DATABASE_URL values are supported")
    path_text = database_url[len(prefix) :]
    path = Path(path_text)
    if not path.is_absolute():
        path = project_root / path
    return path


def _print_maintenance_summary(payload: dict[str, object]) -> None:
    before = payload["before"]
    prune = payload["prune"]
    after = payload.get("after")
    assert isinstance(before, dict)
    assert isinstance(prune, dict)
    candidates = prune["candidates"]
    assert isinstance(candidates, dict)
    print(f"Database: {before['database_path']}")
    print(
        "Size: "
        f"{_format_bytes(int(before['database_bytes']))} db, "
        f"{_format_bytes(int(before['wal_bytes']))} wal, "
        f"freelist_pages={before['freelist_count']}"
    )
    print(f"Retention cutoff: {prune['cutoff_pdt']} ({prune['retention_hours']}h)")
    print(
        "Prune candidates: "
        f"{candidates['source_trades']} source_trades, "
        f"{candidates['source_trade_attributions']} attributions, "
        f"{candidates['assets']} assets"
    )
    print(f"Applied: {prune['applied']}")
    if prune["applied"]:
        print(
            "Deleted: "
            f"{prune['deleted_source_trades']} source_trades, "
            f"{prune['deleted_source_trade_attributions']} attributions; "
            f"vacuumed={prune['vacuumed']} analyzed={prune['analyzed']}"
        )
        if isinstance(after, dict):
            print(
                "After: "
                f"{_format_bytes(int(after['database_bytes']))} db, "
                f"{_format_bytes(int(after['wal_bytes']))} wal, "
                f"freelist_pages={after['freelist_count']}"
            )
    else:
        print("Dry run only. Re-run with --apply to delete and --vacuum to reclaim disk space.")


def _format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


if __name__ == "__main__":
    raise SystemExit(main())
