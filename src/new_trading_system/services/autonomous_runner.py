from __future__ import annotations

import json
from datetime import UTC, datetime, time as clock_time
from pathlib import Path
import time as time_module
import uuid
from zoneinfo import ZoneInfo

from ..config import RuntimeConfig
from ..time_utils import utc_now
from .portfolio_ledger import PortfolioLedger
from .reconciliation import ReconciliationService
from .worker import PaperTradingWorker, WorkerLockBusyError, build_broker

EASTERN_TZ = ZoneInfo("America/New_York")


def autonomous_halt_path(root: Path) -> Path:
    return root / "var" / "runtime" / "AUTONOMOUS_HALTED"


def autonomous_heartbeat_path(root: Path) -> Path:
    return root / "var" / "runtime" / "autonomous_heartbeat.json"


def autonomous_status_latest_path(root: Path) -> Path:
    return root / "var" / "runtime" / "autonomous_status_latest.json"


def autonomous_status_history_path(root: Path) -> Path:
    return root / "var" / "runtime" / "autonomous_status_history.jsonl"


def is_us_market_session(timestamp: datetime) -> bool:
    eastern = timestamp.replace(tzinfo=UTC).astimezone(EASTERN_TZ)
    current_time = eastern.time()
    return eastern.weekday() < 5 and clock_time(9, 30) <= current_time <= clock_time(
        16, 0
    )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def write_heartbeat(root: Path, payload: dict[str, object]) -> None:
    _write_json(
        autonomous_heartbeat_path(root),
        {
            "generated_at": utc_now().isoformat(),
            **payload,
        },
    )


def update_status(
    root: Path,
    *,
    run_id: str,
    iteration: int,
    status: str,
    phase: str,
    blocker_reason: str | None = None,
    metadata: dict[str, object] | None = None,
) -> dict[str, object]:
    payload = {
        "run_id": run_id,
        "iteration": iteration,
        "status": status,
        "phase": phase,
        "blocker_reason": blocker_reason,
        "last_heartbeat_utc": utc_now().isoformat(),
        "metadata": metadata or {},
    }
    _write_json(autonomous_status_latest_path(root), payload)
    _append_jsonl(
        autonomous_status_history_path(root),
        {
            **payload,
            "event_at_utc": utc_now().isoformat(),
        },
    )
    return payload


def _write_accounts_summary(
    root: Path,
    iteration_payload: dict[str, object],
    overall_ok: bool,
) -> None:
    _write_json(
        root / "apps" / "dashboard" / "data" / "accounts" / "summary.json",
        {
            "generated_at": utc_now().isoformat(),
            "ok": overall_ok,
            **iteration_payload,
        },
    )


def _market_gate_reason(
    clock_timestamp: datetime, broker_name: str, broker_is_open: bool
) -> str | None:
    if broker_name == "internal-paper":
        return None if is_us_market_session(clock_timestamp) else "market_closed"
    return None if broker_is_open else "market_closed"


def _has_open_positions(account_reports: list[dict[str, object]]) -> bool:
    for report in account_reports:
        if not isinstance(report, dict):
            continue
        summary = report.get("summary")
        if not isinstance(summary, dict):
            continue
        strategies = summary.get("strategies")
        if not isinstance(strategies, list):
            continue
        for strategy in strategies:
            if (
                isinstance(strategy, dict)
                and int(strategy.get("open_positions") or 0) > 0
            ):
                return True
    return False


def _run_account_cycle(
    *,
    root: Path,
    account_id: str,
    broker_override: str | None,
    strategy_ids: list[str] | None,
    dry_run: bool,
    reconcile_after_cycle: bool,
    verify_after_cycle: bool,
    stale_order_age_minutes: int,
) -> dict[str, object]:
    config = RuntimeConfig.from_env(root, account_id=account_id)
    broker_name = broker_override or config.default_broker
    broker = build_broker(config, broker_name)
    clock = broker.get_clock()
    gate_reason = _market_gate_reason(clock.timestamp, broker_name, clock.is_open)
    if gate_reason is not None:
        return {
            "account_id": config.account_id,
            "broker": broker_name,
            "ok": True,
            "executed": False,
            "reason": gate_reason,
            "market_timestamp": clock.timestamp.isoformat(),
        }

    worker = PaperTradingWorker(config=config, broker_name=broker_name)
    report = worker.run_once(strategy_ids=strategy_ids, dry_run=dry_run)
    response: dict[str, object] = {
        "account_id": config.account_id,
        "broker": broker_name,
        "ok": True,
        "executed": True,
        "market_timestamp": clock.timestamp.isoformat(),
        "summary": report.summary.payload,
    }

    if reconcile_after_cycle or verify_after_cycle:
        reconciliation = ReconciliationService(
            broker=build_broker(config, broker_name),
            ledger=PortfolioLedger(config.state_db_path),
            account_id=config.account_id,
        )
        if reconcile_after_cycle:
            response["reconcile"] = reconciliation.reconcile(
                summary_path=config.dashboard_summary_path
            )
        if verify_after_cycle:
            verify_report = reconciliation.verify(
                stale_order_age_minutes=stale_order_age_minutes,
                cancel_stale=False,
            )
            response["verify"] = verify_report
            response["ok"] = bool(response["ok"]) and bool(verify_report["ok"])

    return response


def run_autonomous_runner(
    *,
    root: Path,
    account_ids: list[str],
    broker_override: str | None,
    strategy_ids: list[str] | None,
    dry_run: bool,
    interval_seconds: int,
    active_interval_seconds: int,
    max_iterations: int | None,
    reconcile_after_cycle: bool,
    verify_after_cycle: bool,
    stale_order_age_minutes: int,
) -> dict[str, object]:
    run_id = f"autonomous-{uuid.uuid4().hex[:12]}"
    capture_history = max_iterations is not None
    iterations: list[dict[str, object]] = []
    iteration_index = 0
    overall_ok = True
    latest_iteration: dict[str, object] | None = None

    while max_iterations is None or iteration_index < max_iterations:
        update_status(
            root,
            run_id=run_id,
            iteration=iteration_index + 1,
            status="running",
            phase="preflight",
            metadata={"accounts": account_ids},
        )
        write_heartbeat(
            root,
            {
                "run_id": run_id,
                "iteration": iteration_index + 1,
                "phase": "preflight",
            },
        )

        if autonomous_halt_path(root).exists():
            latest_iteration = {
                "iteration": iteration_index + 1,
                "ok": True,
                "status": "halted",
                "accounts": [],
                "reason": "halt_file_present",
                "halt_path": str(autonomous_halt_path(root)),
                "next_interval_seconds": interval_seconds,
            }
            update_status(
                root,
                run_id=run_id,
                iteration=iteration_index + 1,
                status="halted",
                phase="blocked",
                blocker_reason="halt_file_present",
                metadata={"accounts": account_ids},
            )
        else:
            account_reports: list[dict[str, object]] = []
            iteration_ok = True
            for account_id in account_ids:
                try:
                    report = _run_account_cycle(
                        root=root,
                        account_id=account_id,
                        broker_override=broker_override,
                        strategy_ids=strategy_ids,
                        dry_run=dry_run,
                        reconcile_after_cycle=reconcile_after_cycle,
                        verify_after_cycle=verify_after_cycle,
                        stale_order_age_minutes=stale_order_age_minutes,
                    )
                except WorkerLockBusyError as exc:
                    report = {
                        "account_id": account_id,
                        "ok": False,
                        "executed": False,
                        "error": "worker_lock_busy",
                        "detail": str(exc),
                    }
                except Exception as exc:
                    report = {
                        "account_id": account_id,
                        "ok": False,
                        "executed": False,
                        "error": "autonomous_cycle_failed",
                        "detail": str(exc),
                    }
                account_reports.append(report)
                if not bool(report.get("ok", False)):
                    iteration_ok = False

            latest_iteration = {
                "iteration": iteration_index + 1,
                "ok": iteration_ok,
                "status": "completed" if iteration_ok else "degraded",
                "accounts": account_reports,
                "next_interval_seconds": (
                    active_interval_seconds
                    if _has_open_positions(account_reports)
                    else interval_seconds
                ),
            }
            _write_accounts_summary(root, latest_iteration, overall_ok=iteration_ok)
            update_status(
                root,
                run_id=run_id,
                iteration=iteration_index + 1,
                status="running" if iteration_ok else "degraded",
                phase="cycle_complete",
                metadata={"accounts": account_reports},
            )
            overall_ok = overall_ok and iteration_ok

        write_heartbeat(
            root,
            {
                "run_id": run_id,
                "iteration": iteration_index + 1,
                "phase": "cycle_complete",
                "latest_iteration": latest_iteration,
            },
        )
        if latest_iteration is not None and capture_history:
            iterations.append(latest_iteration)
        iteration_index += 1
        if max_iterations is not None and iteration_index >= max_iterations:
            break
        next_interval_seconds = interval_seconds
        if isinstance(latest_iteration, dict):
            try:
                raw_next_interval = latest_iteration.get("next_interval_seconds")
                next_interval_seconds = (
                    int(raw_next_interval)
                    if isinstance(raw_next_interval, (int, str))
                    else interval_seconds
                )
            except (TypeError, ValueError):
                next_interval_seconds = interval_seconds

        time_module.sleep(next_interval_seconds)

    if latest_iteration is not None and not capture_history:
        iterations = [latest_iteration]
    update_status(
        root,
        run_id=run_id,
        iteration=iteration_index,
        status="completed" if overall_ok else "degraded",
        phase="stopped",
        metadata={"accounts": account_ids},
    )
    return {
        "run_id": run_id,
        "ok": overall_ok,
        "iterations": iterations,
        "halt_path": str(autonomous_halt_path(root)),
        "heartbeat_path": str(autonomous_heartbeat_path(root)),
        "status_path": str(autonomous_status_latest_path(root)),
        "history_path": str(autonomous_status_history_path(root)),
    }
