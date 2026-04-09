from __future__ import annotations

import importlib

models_module = importlib.import_module("new_trading_system.models")
reconciliation_module = importlib.import_module(
    "new_trading_system.services.reconciliation"
)

AssetClass = models_module.AssetClass
Position = models_module.Position
compare_positions = reconciliation_module.compare_positions


def test_compare_positions_tolerates_one_dollar_option_mark_drift() -> None:
    ledger_positions = [
        Position(
            symbol="SPY260424C00690000",
            underlying="SPY",
            asset_class=AssetClass.OPTION,
            qty=-1,
            avg_entry_price=0.86,
            current_price=0.81,
            market_value=-81.0,
            unrealized_pl=5.0,
        )
    ]
    broker_positions = [
        Position(
            symbol="SPY260424C00690000",
            underlying="SPY",
            asset_class=AssetClass.OPTION,
            qty=-1,
            avg_entry_price=0.86,
            current_price=0.82,
            market_value=-82.0,
            unrealized_pl=4.0,
        )
    ]

    assert compare_positions(ledger_positions, broker_positions) == []


def test_compare_positions_still_flags_larger_mark_mismatch() -> None:
    ledger_positions = [
        Position(
            symbol="SPY260424C00690000",
            underlying="SPY",
            asset_class=AssetClass.OPTION,
            qty=-1,
            avg_entry_price=0.86,
            current_price=0.75,
            market_value=-75.0,
            unrealized_pl=11.0,
        )
    ]
    broker_positions = [
        Position(
            symbol="SPY260424C00690000",
            underlying="SPY",
            asset_class=AssetClass.OPTION,
            qty=-1,
            avg_entry_price=0.86,
            current_price=0.82,
            market_value=-82.0,
            unrealized_pl=4.0,
        )
    ]

    discrepancies = compare_positions(ledger_positions, broker_positions)

    assert len(discrepancies) == 1
    assert discrepancies[0]["issue"] == "market_value_mismatch"
