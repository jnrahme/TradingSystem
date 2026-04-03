from __future__ import annotations

from multiprocessing import Process, Queue
from pathlib import Path
import time

import pytest

from new_trading_system.config import RuntimeConfig
from new_trading_system.services.worker import PaperTradingWorker, WorkerLockBusyError, worker_execution_lock


def make_config(root: Path) -> RuntimeConfig:
    (root / "var" / "strategy-state").mkdir(parents=True, exist_ok=True)
    (root / "apps" / "dashboard" / "data").mkdir(parents=True, exist_ok=True)
    return RuntimeConfig(
        project_root=root,
        state_db_path=root / "var" / "trading-state.sqlite3",
        dashboard_summary_path=root / "apps" / "dashboard" / "data" / "summary.json",
        strategy_state_dir=root / "var" / "strategy-state",
        internal_paper_state_path=root / "var" / "internal-paper-state.json",
        worker_lock_path=root / "var" / "worker.lock",
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
    holder = Process(target=_hold_worker_lock, args=(str(config.worker_lock_path), ready))
    holder.start()
    assert ready.get(timeout=5) == "locked"

    worker = PaperTradingWorker(config=config, broker_name="internal-paper")
    with pytest.raises(WorkerLockBusyError):
        worker.run_once(dry_run=True)

    holder.join(timeout=5)
    assert holder.exitcode == 0
