from __future__ import annotations

import json

import new_trading_system.cli as cli_module
from new_trading_system.services.replay_lab import run_demo_replay


def test_demo_replay_reports_profit_stop_and_dte_scenarios() -> None:
    report = run_demo_replay()

    assert report["replay_mode"] == "synthetic-internal-paper"
    assert report["aggregate"] == {
        "scenario_count": 3,
        "paper_entry_fills": 3,
        "paper_exit_fills": 3,
        "estimated_realized_pl_from_filled_exits": -1520.0,
        "estimated_closed_wins": 1,
        "estimated_closed_losses": 1,
        "estimated_closed_flat": 1,
        "exit_reason_counts": {
            "profit_target": 1,
            "stop_loss": 1,
            "exit_dte": 1,
        },
    }
    assert [scenario["scenario_id"] for scenario in report["scenarios"]] == [
        "profit-target",
        "stop-loss",
        "exit-dte",
    ]
    assert all(
        scenario["strategy"]["readiness"]["replay_recorded"] is True
        for scenario in report["scenarios"]
    )
    assert all(
        "replay results are not recorded in the current repo yet"
        not in scenario["strategy"]["blockers"]
        for scenario in report["scenarios"]
    )


def test_replay_cli_prints_report(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)

    exit_code = cli_module.main(["replay"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["scenario_set"] == "demo"
    assert payload["strategy_id"] == "legacy-iron-condor"
    assert payload["aggregate"]["paper_exit_fills"] == 3
    assert (tmp_path / "var" / "replay" / "legacy-iron-condor-demo.json").exists()
