from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import RuntimeConfig, project_root
from .services.portfolio_ledger import PortfolioLedger
from .services.reconciliation import ReconciliationService
from .services.worker import PaperTradingWorker, WorkerLockBusyError
from .services.worker import build_broker


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NewTradingSystem paper worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="run one paper worker cycle")
    run_once.add_argument("--broker", default=None, choices=["internal-paper", "alpaca-paper"])
    run_once.add_argument("--strategy", action="append", dest="strategies")
    run_once.add_argument("--execute", action="store_true", help="submit to the paper broker")

    run_loop = subparsers.add_parser("run-loop", help="run repeated paper worker cycles")
    run_loop.add_argument("--broker", default=None, choices=["internal-paper", "alpaca-paper"])
    run_loop.add_argument("--strategy", action="append", dest="strategies")
    run_loop.add_argument("--execute", action="store_true", help="submit to the paper broker")
    run_loop.add_argument("--interval-seconds", type=int, default=300)
    run_loop.add_argument("--max-iterations", type=int, default=1)

    dashboard = subparsers.add_parser("dashboard", help="print the latest dashboard summary")
    dashboard.add_argument("--path", default=None)

    reconcile = subparsers.add_parser("reconcile", help="sync broker state into the canonical ledger")
    reconcile.add_argument("--broker", default=None, choices=["internal-paper", "alpaca-paper"])

    verify = subparsers.add_parser(
        "verify", help="compare broker state against the ledger and optionally cancel stale orders"
    )
    verify.add_argument("--broker", default=None, choices=["internal-paper", "alpaca-paper"])
    verify.add_argument("--stale-order-age-minutes", type=int, default=60)
    verify.add_argument("--cancel-stale", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = RuntimeConfig.from_env(project_root())

    if args.command == "dashboard":
        path = Path(args.path) if args.path else config.dashboard_summary_path
        if not path.exists():
            print(json.dumps({"error": "dashboard summary not found", "path": str(path)}, indent=2))
            return 1
        print(path.read_text())
        return 0

    broker = args.broker or config.default_broker
    if args.command in {"reconcile", "verify"}:
        reconciliation = ReconciliationService(
            broker=build_broker(config, broker),
            ledger=PortfolioLedger(config.state_db_path),
        )
        if args.command == "reconcile":
            report = reconciliation.reconcile(summary_path=config.dashboard_summary_path)
            print(json.dumps(report, indent=2))
            return 0

        report = reconciliation.verify(
            stale_order_age_minutes=args.stale_order_age_minutes,
            cancel_stale=args.cancel_stale,
        )
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    worker = PaperTradingWorker(config=config, broker_name=broker)
    try:
        if args.command == "run-once":
            report = worker.run_once(strategy_ids=args.strategies, dry_run=not args.execute)
            print(json.dumps(report.summary.payload, indent=2))
            return 0

        reports = worker.run_loop(
            strategy_ids=args.strategies,
            dry_run=not args.execute,
            interval_seconds=args.interval_seconds,
            max_iterations=args.max_iterations,
        )
        print(json.dumps([report.summary.payload for report in reports], indent=2))
        return 0
    except WorkerLockBusyError as exc:
        print(json.dumps({"error": "worker_lock_busy", "detail": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
