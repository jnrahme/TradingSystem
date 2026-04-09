from __future__ import annotations

import importlib
import json
from datetime import date, datetime, timedelta


def _business_bars(start: date, days: int):
    HistoricalBar = importlib.import_module(
        "new_trading_system.services.historical_backtest"
    ).HistoricalBar

    bars = []
    current = start
    price = 600.0
    pattern = [3.0, -2.0, 4.0, -1.0, 2.0]
    pattern_index = 0
    while len(bars) < days:
        if current.weekday() < 5:
            open_price = price
            close_price = price + pattern[pattern_index % len(pattern)]
            high = max(open_price, close_price) + 2.0
            low = min(open_price, close_price) - 2.0
            bars.append(
                HistoricalBar(
                    timestamp=datetime.combine(current, datetime.min.time()),
                    open=open_price,
                    high=high,
                    low=low,
                    close=close_price,
                    volume=1_000_000,
                )
            )
            price = close_price
            pattern_index += 1
        current += timedelta(days=1)
    return bars


def test_run_historical_backtest_emits_real_bar_report(monkeypatch) -> None:
    historical_backtest = importlib.import_module(
        "new_trading_system.services.historical_backtest"
    )
    AlpacaHistoricalBarsClient = historical_backtest.AlpacaHistoricalBarsClient
    HistoricalBacktestConfig = historical_backtest.HistoricalBacktestConfig
    run_historical_backtest = historical_backtest.run_historical_backtest

    bars = _business_bars(date(2025, 1, 2), 80)
    monkeypatch.setattr(
        AlpacaHistoricalBarsClient,
        "fetch_daily_bars",
        lambda self, symbol, start_date, end_date: bars,
    )
    config = HistoricalBacktestConfig(min_vix=0.0, max_vix=100.0, min_credit=0.0)
    monkeypatch.setattr(
        HistoricalBacktestConfig,
        "from_strategy_settings",
        classmethod(lambda cls, settings=None: config),
    )

    report = run_historical_backtest(
        api_key="key",
        api_secret="secret",
        data_base_url="https://data.alpaca.markets",
        start_date=date(2025, 1, 2),
        end_date=date(2025, 4, 1),
    )

    assert report["scenario_set"] == "historical-bars"
    assert report["replay_mode"] == "modeled-options-on-real-bars"
    assert report["aggregate"]["scenario_count"] > 0
    assert report["aggregate"]["start_date"] == "2025-01-02"
    assert report["aggregate"]["end_date"] == "2025-04-01"
    assert (
        "models option prices with Black-Scholes instead of historical option-chain quotes"
        in report["limitations"]
    )


def test_replay_cli_historical_mode_writes_report(
    tmp_path, monkeypatch, capsys
) -> None:
    cli_module = importlib.import_module("new_trading_system.cli")
    RuntimeConfig = importlib.import_module("new_trading_system.config").RuntimeConfig

    monkeypatch.setattr(cli_module, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        cli_module,
        "load_historical_backtest_runner",
        lambda: (
            lambda **kwargs: {
                "generated_at": "2026-04-07T00:00:00",
                "strategy_id": kwargs["strategy_id"],
                "scenario_set": "historical-bars",
                "replay_mode": "modeled-options-on-real-bars",
                "limitations": ["test"],
                "scenarios": [{"entry_date": "2025-01-02"}],
                "aggregate": {"scenario_count": 1, "total_pnl": 10.0},
            }
        ),
    )
    monkeypatch.setattr(
        cli_module.RuntimeConfig,
        "from_env",
        classmethod(
            lambda cls, root, account_id=None: RuntimeConfig(
                project_root=root,
                state_db_path=root / "var" / "trading-state.sqlite3",
                dashboard_summary_path=root
                / "apps"
                / "dashboard"
                / "data"
                / "summary.json",
                strategy_state_dir=root / "var" / "strategy-state",
                internal_paper_state_path=root / "var" / "internal-paper-state.json",
                worker_lock_path=root / "var" / "worker.lock",
                default_broker="internal-paper",
                alpaca_api_key="key",
                alpaca_api_secret="secret",
                alpaca_trading_base_url="https://paper-api.alpaca.markets/v2",
                alpaca_data_base_url="https://data.alpaca.markets",
            )
        ),
    )

    exit_code = cli_module.main(
        ["replay", "--scenario-set", "historical-bars", "--days", "30"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert payload["scenario_set"] == "historical-bars"
    assert (
        tmp_path / "var" / "replay" / "legacy-iron-condor-historical-bars.json"
    ).exists()


def test_historical_backtest_skips_trade_when_no_bars_exist_before_expiry(
    monkeypatch,
) -> None:
    historical_backtest = importlib.import_module(
        "new_trading_system.services.historical_backtest"
    )
    HistoricalBacktestConfig = historical_backtest.HistoricalBacktestConfig
    _simulate_trade = historical_backtest._simulate_trade

    bars = _business_bars(date(2025, 1, 2), 2)
    gap_bars = bars + _business_bars(date(2025, 3, 1), 10)
    config = HistoricalBacktestConfig(min_vix=0.0, max_vix=100.0, min_credit=0.0)

    result, skip_reason = _simulate_trade(0, gap_bars, gap_bars, config)

    assert result is None
    assert skip_reason == "insufficient_future_bars"


def test_run_historical_backtest_respects_max_open_structures(monkeypatch) -> None:
    historical_backtest = importlib.import_module(
        "new_trading_system.services.historical_backtest"
    )
    AlpacaHistoricalBarsClient = historical_backtest.AlpacaHistoricalBarsClient
    HistoricalBacktestConfig = historical_backtest.HistoricalBacktestConfig
    run_historical_backtest = historical_backtest.run_historical_backtest

    bars = _business_bars(date(2025, 1, 2), 80)
    monkeypatch.setattr(
        AlpacaHistoricalBarsClient,
        "fetch_daily_bars",
        lambda self, symbol, start_date, end_date: bars,
    )
    config = HistoricalBacktestConfig(
        min_vix=0.0,
        max_vix=100.0,
        min_credit=0.0,
        entry_spacing_trading_days=1,
        max_open_structures=1,
    )
    monkeypatch.setattr(
        HistoricalBacktestConfig,
        "from_strategy_settings",
        classmethod(lambda cls, settings=None: config),
    )

    report = run_historical_backtest(
        api_key="key",
        api_secret="secret",
        data_base_url="https://data.alpaca.markets",
        start_date=date(2025, 1, 2),
        end_date=date(2025, 4, 1),
    )

    assert report["aggregate"]["scenario_count"] > 0
    assert report["aggregate"]["skip_reasons"].get("max_open_structures_reached", 0) > 0
