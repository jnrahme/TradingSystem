from __future__ import annotations

import argparse
import importlib
import json
from datetime import datetime
import os
from pathlib import Path
import time
from typing import Sequence

from .config import RuntimeConfig, project_root
from .models import BrokerOrder, Position
from .occ import group_condors
from .time_utils import utc_now
from .services.portfolio_ledger import PortfolioLedger
from .services.reconciliation import ReconciliationService
from .services.worker import PaperTradingWorker, WorkerLockBusyError
from .services.worker import build_broker, build_registry


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NewTradingSystem paper worker")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="run one paper worker cycle")
    run_once.add_argument("--account", default=None, help="runtime account id")
    run_once.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    run_once.add_argument("--strategy", action="append", dest="strategies")
    run_once.add_argument(
        "--execute", action="store_true", help="submit to the paper broker"
    )

    run_loop = subparsers.add_parser(
        "run-loop", help="run repeated paper worker cycles"
    )
    run_loop.add_argument("--account", default=None, help="runtime account id")
    run_loop.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    run_loop.add_argument("--strategy", action="append", dest="strategies")
    run_loop.add_argument(
        "--execute", action="store_true", help="submit to the paper broker"
    )
    run_loop.add_argument("--interval-seconds", type=int, default=300)
    run_loop_iterations = run_loop.add_mutually_exclusive_group()
    run_loop_iterations.add_argument("--max-iterations", type=int, default=1)
    run_loop_iterations.add_argument(
        "--forever", action="store_true", help="keep cycling until stopped"
    )

    run_accounts = subparsers.add_parser(
        "run-accounts", help="run multiple named accounts sequentially"
    )
    run_accounts.add_argument(
        "--account",
        action="append",
        dest="accounts",
        required=True,
        help="runtime account id; repeat for more than one account",
    )
    run_accounts.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    run_accounts.add_argument("--strategy", action="append", dest="strategies")
    run_accounts.add_argument(
        "--execute", action="store_true", help="submit to the paper broker"
    )
    run_accounts.add_argument("--interval-seconds", type=int, default=300)
    run_accounts_iterations = run_accounts.add_mutually_exclusive_group()
    run_accounts_iterations.add_argument("--max-iterations", type=int, default=1)
    run_accounts_iterations.add_argument(
        "--forever", action="store_true", help="keep cycling until stopped"
    )

    autonomous_runner = subparsers.add_parser(
        "autonomous-runner",
        help="run a market-hours autonomous supervisor for multiple accounts",
    )
    autonomous_runner.add_argument(
        "--account",
        action="append",
        dest="accounts",
        required=True,
        help="runtime account id; repeat for more than one account",
    )
    autonomous_runner.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    autonomous_runner.add_argument("--strategy", action="append", dest="strategies")
    autonomous_runner.add_argument(
        "--execute", action="store_true", help="submit to the paper broker"
    )
    autonomous_runner.add_argument("--interval-seconds", type=int, default=300)
    autonomous_runner.add_argument("--active-interval-seconds", type=int, default=60)
    autonomous_runner_iterations = autonomous_runner.add_mutually_exclusive_group()
    autonomous_runner_iterations.add_argument("--max-iterations", type=int, default=1)
    autonomous_runner_iterations.add_argument(
        "--forever", action="store_true", help="keep cycling until stopped"
    )
    autonomous_runner.add_argument("--reconcile-after-cycle", action="store_true")
    autonomous_runner.add_argument("--verify-after-cycle", action="store_true")
    autonomous_runner.add_argument("--stale-order-age-minutes", type=int, default=60)

    autonomous_status = subparsers.add_parser(
        "autonomous-status", help="print autonomous runtime status"
    )
    autonomous_halt = subparsers.add_parser(
        "autonomous-halt", help="create the autonomous halt file"
    )
    autonomous_halt.add_argument("--reason", default=None)
    subparsers.add_parser("autonomous-resume", help="remove the autonomous halt file")

    dashboard = subparsers.add_parser(
        "dashboard", help="print the latest dashboard summary"
    )
    dashboard.add_argument("--account", default=None, help="runtime account id")
    dashboard.add_argument("--path", default=None)

    scorecard = subparsers.add_parser(
        "scorecard", help="print the current paper strategy scorecard"
    )
    scorecard.add_argument("--account", default=None, help="runtime account id")
    scorecard.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )

    promotion = subparsers.add_parser(
        "promotion", help="evaluate whether a strategy is ready to advance"
    )
    promotion.add_argument("--account", default=None, help="runtime account id")
    promotion.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    promotion.add_argument(
        "--strategy", default="legacy-iron-condor", choices=["legacy-iron-condor"]
    )

    replay = subparsers.add_parser("replay", help="run the synthetic replay harness")
    replay.add_argument(
        "--strategy", default="legacy-iron-condor", choices=["legacy-iron-condor"]
    )
    replay.add_argument(
        "--scenario-set", default="demo", choices=["demo", "historical-bars"]
    )
    replay.add_argument("--days", type=int, default=90)
    replay.add_argument("--start", default=None, help="start date YYYY-MM-DD")
    replay.add_argument("--end", default=None, help="end date YYYY-MM-DD")

    reconcile = subparsers.add_parser(
        "reconcile", help="sync broker state into the canonical ledger"
    )
    reconcile.add_argument("--account", default=None, help="runtime account id")
    reconcile.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )

    verify = subparsers.add_parser(
        "verify",
        help="compare broker state against the ledger and optionally cancel stale orders",
    )
    verify.add_argument("--account", default=None, help="runtime account id")
    verify.add_argument(
        "--broker", default=None, choices=["internal-paper", "alpaca-paper"]
    )
    verify.add_argument("--stale-order-age-minutes", type=int, default=60)
    verify.add_argument("--cancel-stale", action="store_true")
    return parser


def run_accounts_loop(
    root: Path,
    account_ids: list[str],
    broker_override: str | None,
    strategy_ids: list[str] | None,
    dry_run: bool,
    interval_seconds: int,
    max_iterations: int | None,
) -> dict[str, object]:
    capture_history = max_iterations is not None
    iterations: list[dict[str, object]] = []
    overall_ok = True
    iteration = 0
    latest_iteration: dict[str, object] | None = None

    while max_iterations is None or iteration < max_iterations:
        account_reports: list[dict[str, object]] = []
        iteration_ok = True
        for raw_account_id in account_ids:
            config = RuntimeConfig.from_env(root, account_id=raw_account_id)
            broker = broker_override or config.default_broker
            worker = PaperTradingWorker(config=config, broker_name=broker)
            try:
                report = worker.run_once(strategy_ids=strategy_ids, dry_run=dry_run)
            except WorkerLockBusyError as exc:
                iteration_ok = False
                overall_ok = False
                account_reports.append(
                    {
                        "account_id": config.account_id,
                        "broker": broker,
                        "ok": False,
                        "error": "worker_lock_busy",
                        "detail": str(exc),
                    }
                )
                continue

            account_reports.append(
                {
                    "account_id": config.account_id,
                    "broker": broker,
                    "ok": True,
                    "summary": report.summary.payload,
                }
            )

        latest_iteration = {
            "iteration": iteration + 1,
            "ok": iteration_ok,
            "accounts": account_reports,
        }
        if capture_history:
            iterations.append(latest_iteration)
        _write_accounts_summary(root, latest_iteration, overall_ok=overall_ok)
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            break
        time.sleep(interval_seconds)

    if not capture_history and latest_iteration is not None:
        iterations = [latest_iteration]
    return {"ok": overall_ok, "iterations": iterations}


def _write_accounts_summary(
    root: Path,
    iteration_payload: dict[str, object],
    overall_ok: bool,
) -> None:
    path = root / "apps" / "dashboard" / "data" / "accounts" / "summary.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "generated_at": utc_now().isoformat(),
                "ok": overall_ok,
                **iteration_payload,
            },
            indent=2,
        )
    )


def resolve_max_iterations(args: argparse.Namespace) -> int | None:
    return None if getattr(args, "forever", False) else args.max_iterations


def load_replay_runner():
    module = importlib.import_module("new_trading_system.services.replay_lab")
    return module.run_demo_replay


def load_historical_backtest_runner():
    module = importlib.import_module("new_trading_system.services.historical_backtest")
    return module.run_historical_backtest


def load_autonomous_runtime_module():
    return importlib.import_module("new_trading_system.services.autonomous_runner")


def load_autonomous_runner():
    return load_autonomous_runtime_module().run_autonomous_runner


def load_promotion_evaluator():
    module = importlib.import_module("new_trading_system.services.promotion_gate")
    return module.evaluate_strategy_promotion


def read_json_if_exists(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def autonomous_runtime_payload(root: Path) -> dict[str, object]:
    runtime_module = load_autonomous_runtime_module()
    halt_path = runtime_module.autonomous_halt_path(root)
    heartbeat_path = runtime_module.autonomous_heartbeat_path(root)
    status_path = runtime_module.autonomous_status_latest_path(root)
    history_path = runtime_module.autonomous_status_history_path(root)
    return {
        "halt_path": str(halt_path),
        "halt_active": halt_path.exists(),
        "halt": read_json_if_exists(halt_path),
        "heartbeat_path": str(heartbeat_path),
        "heartbeat": read_json_if_exists(heartbeat_path),
        "status_path": str(status_path),
        "status": read_json_if_exists(status_path),
        "history_path": str(history_path),
        "history_exists": history_path.exists(),
    }


def write_autonomous_halt(root: Path, reason: str | None) -> dict[str, object]:
    runtime_module = load_autonomous_runtime_module()
    halt_path = runtime_module.autonomous_halt_path(root)
    payload = {
        "requested_at": utc_now().isoformat(),
        "reason": reason or "manual_operator_halt",
    }
    halt_path.parent.mkdir(parents=True, exist_ok=True)
    halt_path.write_text(json.dumps(payload, indent=2))
    return {
        "ok": True,
        "halt_path": str(halt_path),
        "halt_active": True,
        "halt": payload,
    }


def clear_autonomous_halt(root: Path) -> dict[str, object]:
    runtime_module = load_autonomous_runtime_module()
    halt_path = runtime_module.autonomous_halt_path(root)
    removed = False
    if halt_path.exists():
        halt_path.unlink()
        removed = True
    return {
        "ok": True,
        "halt_path": str(halt_path),
        "halt_active": halt_path.exists(),
        "removed": removed,
    }


def replay_report_path(root: Path, strategy_id: str, scenario_set: str) -> Path:
    return root / "var" / "replay" / f"{strategy_id}-{scenario_set}.json"


def legacy_trades_path(root: Path) -> Path:
    configured = os.environ.get("NTS_LEGACY_TRADES_PATH")
    if configured:
        return Path(configured)
    return root.parent / "trading" / "data" / "trades.json"


def load_legacy_trade_reference(root: Path) -> dict[str, object] | None:
    path = legacy_trades_path(root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    stats = payload.get("stats")
    meta = payload.get("meta")
    if not isinstance(stats, dict):
        return None
    if not isinstance(meta, dict):
        meta = {}
    return {
        "source": "legacy-paper-reference",
        "path": str(path),
        "closed_trades": stats.get("closed_trades"),
        "paper_phase_days": stats.get("paper_phase_days"),
        "win_rate_pct": stats.get("win_rate_pct"),
        "total_realized_pnl": stats.get("total_realized_pnl"),
        "min_trades_for_decision": (
            meta.get("decision_thresholds", {}).get("min_trades_for_decision")
            if isinstance(meta.get("decision_thresholds"), dict)
            else None
        ),
        "note": "reference only; not counted toward current-system readiness",
    }


def write_replay_report(root: Path, payload: dict[str, object]) -> Path:
    path = replay_report_path(
        root,
        strategy_id=str(payload["strategy_id"]),
        scenario_set=str(payload["scenario_set"]),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))
    return path


def parse_replay_report(
    report_path: Path, warnings: list[str]
) -> dict[str, str] | None:
    try:
        report_payload = json.loads(report_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        warnings.append(f"ignored replay report {report_path}: {exc}")
        return None

    if not isinstance(report_payload, dict):
        warnings.append(
            f"ignored replay report {report_path}: top-level payload must be an object"
        )
        return None

    strategy_id = str(report_payload.get("strategy_id") or "").strip()
    scenario_set = str(report_payload.get("scenario_set") or "").strip()
    replay_mode = str(report_payload.get("replay_mode") or "").strip()
    scenarios = report_payload.get("scenarios")
    aggregate = report_payload.get("aggregate")
    scenario_count = None
    if isinstance(aggregate, dict):
        raw_scenario_count = aggregate.get("scenario_count")
        try:
            scenario_count = (
                int(raw_scenario_count) if raw_scenario_count is not None else None
            )
        except (TypeError, ValueError):
            scenario_count = None

    if (
        not strategy_id
        or not scenario_set
        or not replay_mode
        or not isinstance(scenarios, list)
        or not isinstance(aggregate, dict)
        or scenario_count is None
        or scenario_count <= 0
    ):
        warnings.append(
            f"ignored replay report {report_path}: missing required replay fields"
        )
        return None

    return {
        "strategy_id": strategy_id,
        "scenario_set": scenario_set,
        "replay_mode": replay_mode,
        "scenario_count": str(scenario_count),
        "win_rate_pct": str(aggregate.get("win_rate_pct"))
        if isinstance(aggregate.get("win_rate_pct"), (int, float))
        else "",
        "total_pnl": str(aggregate.get("total_pnl"))
        if isinstance(aggregate.get("total_pnl"), (int, float))
        else "",
        "path": str(report_path),
    }


def apply_replay_evidence(root: Path, payload: dict[str, object]) -> dict[str, object]:
    replay_dir = root / "var" / "replay"
    if not replay_dir.exists():
        payload["replay_reports_available"] = []
        payload["replay_report_warnings"] = []
        return payload

    replay_reports: list[dict[str, str]] = []
    warnings: list[str] = []
    for report_path in sorted(replay_dir.glob("*.json")):
        report = parse_replay_report(report_path, warnings)
        if report is None:
            continue
        replay_reports.append(report)

    strategies = payload.get("strategies")
    if not isinstance(strategies, list):
        strategies = []

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue
        strategy_reports = [
            report
            for report in replay_reports
            if report["strategy_id"] == strategy.get("strategy_id")
        ]
        if not strategy_reports:
            continue
        readiness = strategy.get("readiness")
        if isinstance(readiness, dict):
            readiness["replay_recorded"] = True
        blockers = strategy.get("blockers")
        if isinstance(blockers, list):
            strategy["blockers"] = [
                blocker
                for blocker in blockers
                if blocker != "replay results are not recorded in the current repo yet"
            ]
        strategy["replay_reports"] = strategy_reports

    payload["replay_reports_available"] = replay_reports
    payload["replay_report_warnings"] = warnings
    return payload


def apply_broker_order_evidence(
    payload: dict[str, object],
    ledger: PortfolioLedger,
    broker_name: str,
    broker_orders: Sequence[BrokerOrder],
) -> dict[str, object]:
    fallback_strategy_id = None
    strategies = payload.get("strategies")
    if isinstance(strategies, list):
        strategy_ids = [
            strategy.get("strategy_id")
            for strategy in strategies
            if isinstance(strategy, dict)
            and isinstance(strategy.get("strategy_id"), str)
            and strategy.get("strategy_id") != "unassigned"
        ]
        if len(strategy_ids) == 1:
            fallback_strategy_id = strategy_ids[0]
    replay_reports_available = payload.get("replay_reports_available")
    if fallback_strategy_id is None and isinstance(replay_reports_available, list):
        replay_strategy_ids = {
            report.get("strategy_id")
            for report in replay_reports_available
            if isinstance(report, dict) and isinstance(report.get("strategy_id"), str)
        }
        if len(replay_strategy_ids) == 1:
            fallback_strategy_id = next(iter(replay_strategy_ids))

    if fallback_strategy_id is not None and hasattr(
        ledger, "backfill_symbol_strategy_map"
    ):
        ledger.backfill_symbol_strategy_map(fallback_strategy_id, broker_orders)

    evidence = ledger.build_broker_order_evidence(
        broker_name,
        broker_orders,
        fallback_strategy_id=fallback_strategy_id,
    )
    if not isinstance(strategies, list):
        strategies = []
        payload["strategies"] = strategies

    if not strategies and evidence:
        for strategy_id in sorted(evidence):
            replay_reports = (
                [
                    report
                    for report in replay_reports_available
                    if isinstance(report, dict)
                    and report.get("strategy_id") == strategy_id
                ]
                if isinstance(replay_reports_available, list)
                else []
            )
            strategies.append(
                {
                    "strategy_id": strategy_id,
                    "runs": 0,
                    "market_open_runs": 0,
                    "observed_days": 0,
                    "alerts_emitted": 0,
                    "intents_generated": 0,
                    "entry_orders": {},
                    "exit_orders": {},
                    "paper_entry_fills": 0,
                    "paper_exit_fills": 0,
                    "avg_expected_credit": None,
                    "avg_declared_max_loss": None,
                    "open_positions": 0,
                    "open_unrealized_pl": 0.0,
                    "open_market_value": 0.0,
                    "estimated_realized_pl_from_filled_exits": 0.0,
                    "estimated_closed_wins": 0,
                    "estimated_closed_losses": 0,
                    "estimated_closed_flat": 0,
                    "estimated_win_rate_pct": None,
                    "exit_reason_counts": {},
                    "readiness": {
                        "paper_execution_observed": False,
                        "paper_exit_observed": False,
                        "replay_recorded": bool(replay_reports),
                        "eligible_for_live_consideration": False,
                    },
                    "blockers": [
                        "no filled paper entries recorded",
                        "no filled paper exits recorded",
                    ],
                    "replay_reports": replay_reports,
                }
            )

    for strategy in strategies:
        if not isinstance(strategy, dict):
            continue
        strategy_id = strategy.get("strategy_id")
        if not isinstance(strategy_id, str):
            continue
        broker_evidence = evidence.get(strategy_id)
        if broker_evidence is None:
            continue
        local_entry_fills = int(strategy.get("paper_entry_fills") or 0)
        local_exit_fills = int(strategy.get("paper_exit_fills") or 0)
        local_observed_days = int(strategy.get("observed_days") or 0)
        broker_entry_fills = int(broker_evidence.get("entry_fills") or 0)
        broker_exit_fills = int(broker_evidence.get("exit_fills") or 0)
        broker_observed_days = int(broker_evidence.get("observed_days") or 0)
        broker_realized_pnl = float(broker_evidence.get("realized_pnl_total") or 0.0)
        broker_win_rate = broker_evidence.get("win_rate_pct")
        effective_entry_fills = max(local_entry_fills, broker_entry_fills)
        effective_exit_fills = max(local_exit_fills, broker_exit_fills)
        effective_observed_days = max(local_observed_days, broker_observed_days)
        strategy["broker_observed_entry_fills"] = broker_entry_fills
        strategy["broker_observed_exit_fills"] = broker_exit_fills
        strategy["broker_observed_days"] = broker_observed_days
        strategy["broker_realized_pnl_from_filled_exits"] = broker_realized_pnl
        strategy["broker_observed_win_rate_pct"] = broker_win_rate
        strategy["effective_paper_entry_fills"] = effective_entry_fills
        strategy["effective_paper_exit_fills"] = effective_exit_fills
        strategy["effective_observed_days"] = effective_observed_days
        local_realized = float(
            strategy.get("estimated_realized_pl_from_filled_exits") or 0.0
        )
        effective_realized = (
            broker_realized_pnl if broker_exit_fills > 0 else local_realized
        )
        strategy["effective_estimated_realized_pl_from_filled_exits"] = (
            effective_realized
        )
        if broker_exit_fills > 0:
            strategy["estimated_realized_pl_from_filled_exits"] = effective_realized

        local_win_rate = strategy.get("estimated_win_rate_pct")
        effective_win_rate = (
            broker_win_rate if broker_exit_fills > 0 else local_win_rate
        )
        strategy["effective_estimated_win_rate_pct"] = effective_win_rate
        if broker_exit_fills > 0:
            strategy["estimated_win_rate_pct"] = effective_win_rate

        readiness = strategy.get("readiness")
        if isinstance(readiness, dict):
            readiness["paper_execution_observed"] = effective_entry_fills > 0
            readiness["paper_exit_observed"] = effective_exit_fills > 0

        blockers = strategy.get("blockers")
        if isinstance(blockers, list):
            updated_blockers = list(blockers)
            if effective_entry_fills > 0:
                updated_blockers = [
                    blocker
                    for blocker in updated_blockers
                    if blocker != "no filled paper entries recorded"
                ]
            if effective_exit_fills > 0:
                updated_blockers = [
                    blocker
                    for blocker in updated_blockers
                    if blocker != "no filled paper exits recorded"
                ]
            strategy["blockers"] = updated_blockers

    if fallback_strategy_id is not None:
        fallback_strategy = next(
            (
                strategy
                for strategy in strategies
                if isinstance(strategy, dict)
                and strategy.get("strategy_id") == fallback_strategy_id
            ),
            None,
        )
        unassigned_strategy = next(
            (
                strategy
                for strategy in strategies
                if isinstance(strategy, dict)
                and strategy.get("strategy_id") == "unassigned"
            ),
            None,
        )
        if isinstance(fallback_strategy, dict) and isinstance(
            unassigned_strategy, dict
        ):
            open_positions = int(unassigned_strategy.get("open_positions") or 0)
            if open_positions > 0:
                fallback_strategy["open_positions"] = (
                    int(fallback_strategy.get("open_positions") or 0) + open_positions
                )
                fallback_strategy["open_unrealized_pl"] = round(
                    float(fallback_strategy.get("open_unrealized_pl") or 0.0)
                    + float(unassigned_strategy.get("open_unrealized_pl") or 0.0),
                    2,
                )
                fallback_strategy["open_market_value"] = round(
                    float(fallback_strategy.get("open_market_value") or 0.0)
                    + float(unassigned_strategy.get("open_market_value") or 0.0),
                    2,
                )
                fallback_strategy["broker_position_attribution_fallback"] = True
                strategies.remove(unassigned_strategy)

    payload["broker_order_evidence"] = evidence
    return payload


def apply_live_condor_diagnostics(
    payload: dict[str, object],
    broker_positions: Sequence[Position],
) -> dict[str, object]:
    strategies = payload.get("strategies")
    if not isinstance(strategies, list) or len(strategies) != 1:
        return payload
    strategy = strategies[0]
    if not isinstance(strategy, dict):
        return payload

    condors = group_condors(list(broker_positions))
    if not condors:
        strategy["active_condors"] = []
        return payload

    registry_strategy = build_registry().resolve([str(strategy.get("strategy_id"))])
    if not registry_strategy:
        return payload
    settings = getattr(registry_strategy[0], "settings", None)
    take_profit_pct = float(getattr(settings, "take_profit_pct", 0.5))
    stop_loss_pct = float(getattr(settings, "stop_loss_pct", 1.0))
    exit_dte = int(getattr(settings, "exit_dte", 7))

    strategy["active_condors"] = [
        {
            "expiry": condor.expiry.isoformat(),
            "dte": condor.dte,
            "entry_credit": condor.entry_credit,
            "mark_to_close": condor.mark_to_close,
            "unrealized_pl": condor.unrealized_pl,
            "profit_target_pnl": round(condor.entry_credit * take_profit_pct, 2),
            "profit_target_remaining": round(
                max(0.0, condor.entry_credit * take_profit_pct - condor.unrealized_pl),
                2,
            ),
            "stop_loss_pnl": round(-condor.entry_credit * stop_loss_pct, 2),
            "stop_loss_buffer": round(
                condor.unrealized_pl - (-condor.entry_credit * stop_loss_pct),
                2,
            ),
            "dte_exit_threshold": exit_dte,
            "dte_exit_remaining": max(0, condor.dte - exit_dte),
            "profit_target_hit": condor.unrealized_pl
            >= condor.entry_credit * take_profit_pct,
            "stop_loss_hit": condor.unrealized_pl
            <= -condor.entry_credit * stop_loss_pct,
            "dte_exit_hit": condor.dte <= exit_dte,
        }
        for condor in condors
    ]
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    root = project_root()

    if args.command == "run-accounts":
        payload = run_accounts_loop(
            root=root,
            account_ids=args.accounts,
            broker_override=args.broker,
            strategy_ids=args.strategies,
            dry_run=not args.execute,
            interval_seconds=args.interval_seconds,
            max_iterations=resolve_max_iterations(args),
        )
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 2

    if args.command == "autonomous-runner":
        payload = load_autonomous_runner()(
            root=root,
            account_ids=args.accounts,
            broker_override=args.broker,
            strategy_ids=args.strategies,
            dry_run=not args.execute,
            interval_seconds=args.interval_seconds,
            active_interval_seconds=args.active_interval_seconds,
            max_iterations=resolve_max_iterations(args),
            reconcile_after_cycle=args.reconcile_after_cycle,
            verify_after_cycle=args.verify_after_cycle,
            stale_order_age_minutes=args.stale_order_age_minutes,
        )
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 2

    if args.command == "autonomous-status":
        print(json.dumps(autonomous_runtime_payload(root), indent=2))
        return 0

    if args.command == "autonomous-halt":
        print(json.dumps(write_autonomous_halt(root, args.reason), indent=2))
        return 0

    if args.command == "autonomous-resume":
        print(json.dumps(clear_autonomous_halt(root), indent=2))
        return 0

    if args.command == "replay":
        if args.scenario_set == "demo":
            payload = load_replay_runner()(strategy_id=args.strategy)
        else:
            replay_config = RuntimeConfig.from_env(root)
            if not replay_config.alpaca_api_key or not replay_config.alpaca_api_secret:
                raise ValueError(
                    "alpaca paper credentials are missing from .env.paper.local"
                )
            parsed_start = (
                datetime.strptime(args.start, "%Y-%m-%d").date() if args.start else None
            )
            parsed_end = (
                datetime.strptime(args.end, "%Y-%m-%d").date() if args.end else None
            )
            payload = load_historical_backtest_runner()(
                api_key=replay_config.alpaca_api_key,
                api_secret=replay_config.alpaca_api_secret,
                data_base_url=replay_config.alpaca_data_base_url,
                strategy_id=args.strategy,
                days=args.days,
                start_date=parsed_start,
                end_date=parsed_end,
            )
        report_path = write_replay_report(root, payload)
        payload["report_path"] = str(report_path)
        print(json.dumps(payload, indent=2))
        return 0

    config = RuntimeConfig.from_env(root, account_id=getattr(args, "account", None))

    if args.command == "dashboard":
        path = Path(args.path) if args.path else config.dashboard_summary_path
        if not path.exists():
            print(
                json.dumps(
                    {"error": "dashboard summary not found", "path": str(path)},
                    indent=2,
                )
            )
            return 1
        print(path.read_text())
        return 0

    broker = args.broker or config.default_broker
    if args.command == "scorecard":
        ledger = PortfolioLedger(config.state_db_path)
        broker_adapter = build_broker(config, broker)
        account = broker_adapter.get_account_snapshot()
        broker_positions = broker_adapter.get_positions()
        payload = ledger.build_scorecard(
            account=account,
            broker=broker,
            account_id=config.account_id,
        )
        payload = apply_replay_evidence(root, payload)
        payload = apply_broker_order_evidence(
            payload,
            ledger=ledger,
            broker_name=broker,
            broker_orders=broker_adapter.list_orders(status="all"),
        )
        payload = apply_live_condor_diagnostics(payload, broker_positions)
        payload["legacy_reference"] = load_legacy_trade_reference(root)
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "promotion":
        ledger = PortfolioLedger(config.state_db_path)
        broker_adapter = build_broker(config, broker)
        account = broker_adapter.get_account_snapshot()
        broker_positions = broker_adapter.get_positions()
        scorecard = ledger.build_scorecard(
            account=account,
            broker=broker,
            account_id=config.account_id,
        )
        scorecard = apply_replay_evidence(root, scorecard)
        scorecard = apply_broker_order_evidence(
            scorecard,
            ledger=ledger,
            broker_name=broker,
            broker_orders=broker_adapter.list_orders(status="all"),
        )
        scorecard = apply_live_condor_diagnostics(scorecard, broker_positions)
        manifest = build_registry().resolve([args.strategy])[0].manifest()
        payload = load_promotion_evaluator()(manifest=manifest, scorecard=scorecard)
        payload["legacy_reference"] = load_legacy_trade_reference(root)
        print(json.dumps(payload, indent=2))
        return 0

    if args.command in {"reconcile", "verify"}:
        reconciliation = ReconciliationService(
            broker=build_broker(config, broker),
            ledger=PortfolioLedger(config.state_db_path),
            account_id=config.account_id,
        )
        if args.command == "reconcile":
            report = reconciliation.reconcile(
                summary_path=config.dashboard_summary_path
            )
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
            report = worker.run_once(
                strategy_ids=args.strategies, dry_run=not args.execute
            )
            print(json.dumps(report.summary.payload, indent=2))
            return 0

        reports = worker.run_loop(
            strategy_ids=args.strategies,
            dry_run=not args.execute,
            interval_seconds=args.interval_seconds,
            max_iterations=resolve_max_iterations(args),
            capture_history=not getattr(args, "forever", False),
        )
        print(json.dumps([report.summary.payload for report in reports], indent=2))
        return 0
    except WorkerLockBusyError as exc:
        print(json.dumps({"error": "worker_lock_busy", "detail": str(exc)}, indent=2))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
