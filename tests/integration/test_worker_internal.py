from __future__ import annotations

import importlib
import json
from multiprocessing import Process, Queue
from pathlib import Path
import time

import pytest

cli_module = importlib.import_module("new_trading_system.cli")
RuntimeConfig = importlib.import_module("new_trading_system.config").RuntimeConfig
worker_module = importlib.import_module("new_trading_system.services.worker")
PaperTradingWorker = worker_module.PaperTradingWorker
WorkerLockBusyError = worker_module.WorkerLockBusyError
worker_execution_lock = worker_module.worker_execution_lock


def make_config(root: Path, account_id: str = "default"):
    if account_id == "default":
        strategy_state_dir = root / "var" / "strategy-state"
        state_db_path = root / "var" / "trading-state.sqlite3"
        internal_paper_state_path = root / "var" / "internal-paper-state.json"
        worker_lock_path = root / "var" / "worker.lock"
        dashboard_summary_path = root / "apps" / "dashboard" / "data" / "summary.json"
    else:
        account_root = root / "var" / "accounts" / account_id
        strategy_state_dir = account_root / "strategy-state"
        state_db_path = account_root / "trading-state.sqlite3"
        internal_paper_state_path = account_root / "internal-paper-state.json"
        worker_lock_path = account_root / "worker.lock"
        dashboard_summary_path = (
            root / "apps" / "dashboard" / "data" / "accounts" / f"{account_id}.json"
        )

    strategy_state_dir.mkdir(parents=True, exist_ok=True)
    dashboard_summary_path.parent.mkdir(parents=True, exist_ok=True)
    return RuntimeConfig(
        project_root=root,
        state_db_path=state_db_path,
        dashboard_summary_path=dashboard_summary_path,
        strategy_state_dir=strategy_state_dir,
        internal_paper_state_path=internal_paper_state_path,
        worker_lock_path=worker_lock_path,
        default_broker="internal-paper",
        alpaca_api_key=None,
        alpaca_api_secret=None,
        alpaca_trading_base_url="https://paper-api.alpaca.markets/v2",
        alpaca_data_base_url="https://data.alpaca.markets",
        account_id=account_id,
    )


def test_internal_worker_persists_positions_between_runs(tmp_path) -> None:
    config = make_config(tmp_path)

    first = PaperTradingWorker(config=config, broker_name="internal-paper")
    first_report = first.run_once(dry_run=False)

    assert len(first_report.results) == 1
    assert first_report.summary.payload["strategies"][0]["open_positions"] == 4

    second = PaperTradingWorker(config=config, broker_name="internal-paper")
    second_report = second.run_once(dry_run=False)

    assert second_report.results == []
    assert second_report.summary.payload["strategies"][0]["orders"] == {"filled": 1}
    assert config.internal_paper_state_path.exists()


def test_worker_refreshes_stale_broker_state_under_lock(tmp_path) -> None:
    config = make_config(tmp_path)

    first = PaperTradingWorker(config=config, broker_name="internal-paper")
    stale_second = PaperTradingWorker(config=config, broker_name="internal-paper")

    first_report = first.run_once(dry_run=False)
    second_report = stale_second.run_once(dry_run=False)

    assert len(first_report.results) == 1
    assert second_report.results == []
    assert second_report.summary.payload["strategies"][0]["orders"] == {"filled": 1}


def _hold_worker_lock(lock_path: str, ready: Queue) -> None:
    with worker_execution_lock(Path(lock_path)):
        ready.put("locked")
        time.sleep(1.5)


def test_worker_lock_blocks_parallel_run(tmp_path) -> None:
    config = make_config(tmp_path)
    ready: Queue[str] = Queue()
    holder = Process(
        target=_hold_worker_lock, args=(str(config.worker_lock_path), ready)
    )
    holder.start()
    assert ready.get(timeout=5) == "locked"

    worker = PaperTradingWorker(config=config, broker_name="internal-paper")
    with pytest.raises(WorkerLockBusyError):
        worker.run_once(dry_run=True)

    holder.join(timeout=5)
    assert holder.exitcode == 0


def test_named_accounts_keep_internal_paper_state_isolated(tmp_path) -> None:
    primary_config = make_config(tmp_path, account_id="primary")
    secondary_config = make_config(tmp_path, account_id="secondary")

    primary_first = PaperTradingWorker(
        config=primary_config, broker_name="internal-paper"
    ).run_once(dry_run=False)
    secondary_first = PaperTradingWorker(
        config=secondary_config, broker_name="internal-paper"
    ).run_once(dry_run=False)
    primary_second = PaperTradingWorker(
        config=primary_config, broker_name="internal-paper"
    ).run_once(dry_run=False)

    assert len(primary_first.results) == 1
    assert len(secondary_first.results) == 1
    assert primary_second.results == []
    assert primary_first.summary.payload["account_id"] == "primary"
    assert secondary_first.summary.payload["account_id"] == "secondary"
    assert primary_config.internal_paper_state_path.exists()
    assert secondary_config.internal_paper_state_path.exists()
    assert (
        primary_config.internal_paper_state_path
        != secondary_config.internal_paper_state_path
    )


def test_run_accounts_cli_executes_named_accounts_sequentially(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    exit_code = cli_module.main(
        [
            "run-accounts",
            "--account",
            "alpha",
            "--account",
            "beta",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    fleet_summary = json.loads(
        (
            tmp_path / "apps" / "dashboard" / "data" / "accounts" / "summary.json"
        ).read_text()
    )

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["iterations"][0]["ok"] is True
    assert [entry["account_id"] for entry in payload["iterations"][0]["accounts"]] == [
        "alpha",
        "beta",
    ]
    assert all(entry["ok"] is True for entry in payload["iterations"][0]["accounts"])
    assert payload["iterations"][0]["accounts"][0]["summary"]["account_id"] == "alpha"
    assert payload["iterations"][0]["accounts"][1]["summary"]["account_id"] == "beta"
    assert (
        tmp_path / "var" / "accounts" / "alpha" / "internal-paper-state.json"
    ).exists()
    assert (
        tmp_path / "var" / "accounts" / "beta" / "internal-paper-state.json"
    ).exists()
    assert [entry["account_id"] for entry in fleet_summary["accounts"]] == [
        "alpha",
        "beta",
    ]


def test_cli_forever_flag_maps_to_unbounded_loops() -> None:
    parser = cli_module.build_parser()

    run_loop_args = parser.parse_args(["run-loop", "--forever"])
    run_accounts_args = parser.parse_args(
        ["run-accounts", "--account", "alpha", "--forever"]
    )

    assert cli_module.resolve_max_iterations(run_loop_args) is None
    assert cli_module.resolve_max_iterations(run_accounts_args) is None


def test_scorecard_cli_reports_strategy_blockers_and_entry_evidence(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    run_exit_code = cli_module.main(
        [
            "run-once",
            "--account",
            "score-alpha",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )
    assert run_exit_code == 0
    capsys.readouterr()

    scorecard_exit_code = cli_module.main(
        [
            "scorecard",
            "--account",
            "score-alpha",
            "--broker",
            "internal-paper",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert scorecard_exit_code == 0
    assert payload["account_id"] == "score-alpha"
    assert payload["strategies"][0]["paper_entry_fills"] == 1
    assert payload["strategies"][0]["paper_exit_fills"] == 0
    assert (
        "replay results are not recorded in the current repo yet"
        in payload["strategies"][0]["blockers"]
    )


def test_scorecard_cli_marks_replay_when_saved_report_exists(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    replay_exit_code = cli_module.main(["replay"])
    assert replay_exit_code == 0
    capsys.readouterr()

    run_exit_code = cli_module.main(
        [
            "run-once",
            "--account",
            "score-beta",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )
    assert run_exit_code == 0
    capsys.readouterr()

    scorecard_exit_code = cli_module.main(
        [
            "scorecard",
            "--account",
            "score-beta",
            "--broker",
            "internal-paper",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert scorecard_exit_code == 0
    assert payload["strategies"][0]["readiness"]["replay_recorded"] is True
    assert (
        "replay results are not recorded in the current repo yet"
        not in payload["strategies"][0]["blockers"]
    )
    assert payload["strategies"][0]["replay_reports"][0]["scenario_set"] == "demo"


def test_scorecard_cli_surfaces_legacy_reference_separately(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    legacy_trades = tmp_path.parent / "trading" / "data" / "trades.json"
    legacy_trades.parent.mkdir(parents=True, exist_ok=True)
    legacy_trades.write_text(
        json.dumps(
            {
                "meta": {"decision_thresholds": {"min_trades_for_decision": 30}},
                "stats": {
                    "closed_trades": 1,
                    "paper_phase_days": 55,
                    "win_rate_pct": 100.0,
                    "total_realized_pnl": 41.0,
                },
            }
        ),
        encoding="utf-8",
    )

    run_exit_code = cli_module.main(
        [
            "run-once",
            "--account",
            "legacy-alpha",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )
    assert run_exit_code == 0
    capsys.readouterr()

    scorecard_exit_code = cli_module.main(
        [
            "scorecard",
            "--account",
            "legacy-alpha",
            "--broker",
            "internal-paper",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert scorecard_exit_code == 0
    assert payload["legacy_reference"]["source"] == "legacy-paper-reference"
    assert payload["legacy_reference"]["closed_trades"] == 1
    assert (
        payload["legacy_reference"]["note"]
        == "reference only; not counted toward current-system readiness"
    )


def test_apply_broker_order_evidence_merges_unassigned_positions_into_single_strategy() -> (
    None
):
    class FakeLedger:
        def build_broker_order_evidence(
            self, broker: str, orders, fallback_strategy_id=None
        ):
            assert broker == "alpaca-paper"
            assert fallback_strategy_id == "legacy-iron-condor"
            return {
                "legacy-iron-condor": {
                    "entry_fills": 2,
                    "exit_fills": 0,
                    "observed_days": 1,
                    "realized_pnl_total": 0.0,
                    "closed_wins": 0,
                    "closed_losses": 0,
                    "closed_flat": 0,
                    "win_rate_pct": None,
                }
            }

    payload = {
        "strategies": [
            {
                "strategy_id": "legacy-iron-condor",
                "open_positions": 0,
                "open_unrealized_pl": 0.0,
                "open_market_value": 0.0,
                "paper_entry_fills": 0,
                "paper_exit_fills": 0,
                "observed_days": 0,
                "readiness": {
                    "paper_execution_observed": False,
                    "paper_exit_observed": False,
                },
                "blockers": [
                    "no filled paper entries recorded",
                    "no filled paper exits recorded",
                ],
            },
            {
                "strategy_id": "unassigned",
                "open_positions": 8,
                "open_unrealized_pl": -42.0,
                "open_market_value": -667.0,
            },
        ]
    }

    result = cli_module.apply_broker_order_evidence(
        payload,
        ledger=FakeLedger(),
        broker_name="alpaca-paper",
        broker_orders=[],
    )

    strategy = result["strategies"][0]
    assert strategy["broker_observed_entry_fills"] == 2
    assert strategy["effective_paper_entry_fills"] == 2
    assert strategy["open_positions"] == 8
    assert strategy["open_unrealized_pl"] == -42.0
    assert strategy["open_market_value"] == -667.0
    assert strategy["broker_position_attribution_fallback"] is True
    assert len(result["strategies"]) == 1


def test_apply_broker_order_evidence_counts_exit_fills_and_clears_blocker() -> None:
    class FakeLedger:
        def build_broker_order_evidence(
            self, broker: str, orders, fallback_strategy_id=None
        ):
            assert broker == "alpaca-paper"
            assert fallback_strategy_id == "legacy-iron-condor"
            return {
                "legacy-iron-condor": {
                    "entry_fills": 2,
                    "exit_fills": 3,
                    "observed_days": 4,
                    "realized_pnl_total": 120.0,
                    "closed_wins": 3,
                    "closed_losses": 0,
                    "closed_flat": 0,
                    "win_rate_pct": 100.0,
                }
            }

    payload = {
        "strategies": [
            {
                "strategy_id": "legacy-iron-condor",
                "open_positions": 0,
                "open_unrealized_pl": 0.0,
                "open_market_value": 0.0,
                "paper_entry_fills": 0,
                "paper_exit_fills": 0,
                "observed_days": 0,
                "readiness": {
                    "paper_execution_observed": False,
                    "paper_exit_observed": False,
                },
                "blockers": [
                    "no filled paper entries recorded",
                    "no filled paper exits recorded",
                ],
            }
        ]
    }

    result = cli_module.apply_broker_order_evidence(
        payload,
        ledger=FakeLedger(),
        broker_name="alpaca-paper",
        broker_orders=[],
    )

    strategy = result["strategies"][0]
    assert strategy["broker_observed_exit_fills"] == 3
    assert strategy["effective_paper_exit_fills"] == 3
    assert strategy["effective_observed_days"] == 4
    assert strategy["broker_realized_pnl_from_filled_exits"] == 120.0
    assert strategy["broker_observed_win_rate_pct"] == 100.0
    assert strategy["effective_estimated_realized_pl_from_filled_exits"] == 120.0
    assert strategy["effective_estimated_win_rate_pct"] == 100.0
    assert strategy["readiness"]["paper_execution_observed"] is True
    assert strategy["readiness"]["paper_exit_observed"] is True
    assert "no filled paper entries recorded" not in strategy["blockers"]
    assert "no filled paper exits recorded" not in strategy["blockers"]


def test_apply_live_condor_diagnostics_adds_exit_distance_metrics() -> None:
    models_module = importlib.import_module("new_trading_system.models")
    strategy = worker_module.build_registry().resolve(["legacy-iron-condor"])[0]
    broker = worker_module.build_broker(make_config(Path("/tmp")), "internal-paper")
    now = broker.get_clock().timestamp
    outcome = strategy.generate(
        models_module.StrategyContext(
            manifest=strategy.manifest(),
            account=broker.get_account_snapshot(),
            clock=broker.get_clock(),
            positions=broker.get_positions(),
            state_snapshot={},
            market=broker,
            broker=broker.name,
            now=now,
        )
    )
    broker.submit_order(outcome.intents[0])

    payload = {"strategies": [{"strategy_id": "legacy-iron-condor"}]}
    result = cli_module.apply_live_condor_diagnostics(payload, broker.get_positions())

    condor = result["strategies"][0]["active_condors"][0]
    assert condor["profit_target_pnl"] > 0
    assert condor["profit_target_remaining"] >= 0
    assert condor["dte_exit_threshold"] == 10
    assert condor["dte_exit_remaining"] >= 0


def test_promotion_cli_blocks_until_paper_thresholds_are_met(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    replay_exit_code = cli_module.main(["replay"])
    assert replay_exit_code == 0
    capsys.readouterr()

    run_exit_code = cli_module.main(
        [
            "run-once",
            "--account",
            "promotion-alpha",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )
    assert run_exit_code == 0
    capsys.readouterr()

    promotion_exit_code = cli_module.main(
        [
            "promotion",
            "--account",
            "promotion-alpha",
            "--broker",
            "internal-paper",
            "--strategy",
            "legacy-iron-condor",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert promotion_exit_code == 0
    assert payload["verdict"] == "blocked"
    assert "needs at least 3 filled paper exits" in payload["blockers"]
    assert "needs at least 3 observed paper days" in payload["blockers"]


def test_scorecard_cli_skips_invalid_replay_reports(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    replay_dir = tmp_path / "var" / "replay"
    replay_dir.mkdir(parents=True, exist_ok=True)
    (replay_dir / "broken.json").write_text("{not-json", encoding="utf-8")
    (replay_dir / "spoof.json").write_text(
        json.dumps({"strategy_id": "legacy-iron-condor"}),
        encoding="utf-8",
    )

    run_exit_code = cli_module.main(
        [
            "run-once",
            "--account",
            "score-gamma",
            "--broker",
            "internal-paper",
            "--execute",
        ]
    )
    assert run_exit_code == 0
    capsys.readouterr()

    scorecard_exit_code = cli_module.main(
        [
            "scorecard",
            "--account",
            "score-gamma",
            "--broker",
            "internal-paper",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert scorecard_exit_code == 0
    assert payload["strategies"][0]["readiness"]["replay_recorded"] is False
    assert (
        "replay results are not recorded in the current repo yet"
        in payload["strategies"][0]["blockers"]
    )
    assert payload["replay_reports_available"] == []
    assert len(payload["replay_report_warnings"]) == 2


def test_autonomous_runner_executes_cycle_and_writes_runtime_files(
    tmp_path, monkeypatch, capsys
) -> None:
    runner_module = importlib.import_module(
        "new_trading_system.services.autonomous_runner"
    )

    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    monkeypatch.setattr(runner_module, "is_us_market_session", lambda timestamp: True)

    exit_code = cli_module.main(
        [
            "autonomous-runner",
            "--account",
            "auto-alpha",
            "--broker",
            "internal-paper",
            "--execute",
            "--verify-after-cycle",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["iterations"][0]["status"] == "completed"
    assert payload["iterations"][0]["accounts"][0]["executed"] is True
    assert Path(payload["heartbeat_path"]).exists()
    assert Path(payload["status_path"]).exists()
    assert Path(payload["history_path"]).exists()
    assert (
        tmp_path / "apps" / "dashboard" / "data" / "accounts" / "summary.json"
    ).exists()


def test_autonomous_runner_halt_file_blocks_cycle(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    halt_path = tmp_path / "var" / "runtime" / "AUTONOMOUS_HALTED"
    halt_path.parent.mkdir(parents=True, exist_ok=True)
    halt_path.write_text("halt", encoding="utf-8")

    exit_code = cli_module.main(
        [
            "autonomous-runner",
            "--account",
            "auto-beta",
            "--broker",
            "internal-paper",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["ok"] is True
    assert payload["iterations"][0]["status"] == "halted"
    assert payload["iterations"][0]["reason"] == "halt_file_present"


def test_autonomous_runner_uses_active_interval_when_positions_are_open(
    tmp_path, monkeypatch, capsys
) -> None:
    runner_module = importlib.import_module(
        "new_trading_system.services.autonomous_runner"
    )
    sleep_calls: list[int] = []

    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    monkeypatch.setattr(runner_module, "is_us_market_session", lambda timestamp: True)
    monkeypatch.setattr(
        runner_module.time_module,
        "sleep",
        lambda seconds: sleep_calls.append(seconds),
    )

    exit_code = cli_module.main(
        [
            "autonomous-runner",
            "--account",
            "auto-gamma",
            "--broker",
            "internal-paper",
            "--execute",
            "--max-iterations",
            "2",
            "--interval-seconds",
            "300",
            "--active-interval-seconds",
            "7",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert sleep_calls == [7]
    assert payload["iterations"][0]["next_interval_seconds"] == 7


def test_autonomous_status_reports_runtime_files(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    runtime_dir = tmp_path / "var" / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / "autonomous_status_latest.json").write_text(
        json.dumps({"status": "running"}),
        encoding="utf-8",
    )
    (runtime_dir / "autonomous_heartbeat.json").write_text(
        json.dumps({"generated_at": "2026-04-07T00:00:00"}),
        encoding="utf-8",
    )

    exit_code = cli_module.main(["autonomous-status"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["halt_active"] is False
    assert payload["status"] == {"status": "running"}
    assert payload["heartbeat"] == {"generated_at": "2026-04-07T00:00:00"}


def test_autonomous_halt_and_resume_toggle_halt_file(
    tmp_path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    halt_exit_code = cli_module.main(["autonomous-halt", "--reason", "manual-test"])
    halt_payload = json.loads(capsys.readouterr().out)
    resume_exit_code = cli_module.main(["autonomous-resume"])
    resume_payload = json.loads(capsys.readouterr().out)

    assert halt_exit_code == 0
    assert halt_payload["halt_active"] is True
    assert halt_payload["halt"]["reason"] == "manual-test"
    assert resume_exit_code == 0
    assert resume_payload["removed"] is True
    assert resume_payload["halt_active"] is False
