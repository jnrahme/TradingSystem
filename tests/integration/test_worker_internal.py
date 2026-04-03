from __future__ import annotations

from pathlib import Path

from new_trading_system.config import RuntimeConfig
from new_trading_system.services.worker import PaperTradingWorker


def make_config(root: Path) -> RuntimeConfig:
    (root / "var" / "strategy-state").mkdir(parents=True, exist_ok=True)
    (root / "apps" / "dashboard" / "data").mkdir(parents=True, exist_ok=True)
    return RuntimeConfig(
        project_root=root,
        state_db_path=root / "var" / "trading-state.sqlite3",
        dashboard_summary_path=root / "apps" / "dashboard" / "data" / "summary.json",
        strategy_state_dir=root / "var" / "strategy-state",
        internal_paper_state_path=root / "var" / "internal-paper-state.json",
        default_broker="internal-paper",
        alpaca_api_key=None,
        alpaca_api_secret=None,
        alpaca_trading_base_url="https://paper-api.alpaca.markets/v2",
        alpaca_data_base_url="https://data.alpaca.markets",
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

