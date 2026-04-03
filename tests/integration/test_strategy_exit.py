from __future__ import annotations

from datetime import datetime

from new_trading_system.adapters.internal_paper import InternalPaperBrokerAdapter, build_demo_snapshot
from new_trading_system.models import StrategyContext
from new_trading_system.strategies.legacy_iron_condor import LegacyIronCondorStrategy


def test_legacy_strategy_generates_exit_when_profit_target_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    snapshot = build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    broker = InternalPaperBrokerAdapter(snapshot=snapshot)
    manifest = strategy.manifest()
    account = broker.get_account_snapshot()
    clock = broker.get_clock()

    entry_context = StrategyContext(
        manifest=manifest,
        account=account,
        clock=clock,
        positions=[],
        state_snapshot={},
        market=broker,
        broker=broker.name,
        now=datetime(2026, 4, 3, 14, 30),
    )
    entry_outcome = strategy.generate(entry_context)
    assert len(entry_outcome.intents) == 1
    broker.submit_order(entry_outcome.intents[0])

    for symbol, quote in broker.snapshot.option_quotes.items():
        if "P00625000" in symbol or "C00685000" in symbol:
            quote.bid = 0.95
            quote.ask = 1.05
        else:
            quote.bid = 0.0
            quote.ask = 0.1

    exit_context = StrategyContext(
        manifest=manifest,
        account=broker.get_account_snapshot(),
        clock=clock,
        positions=broker.get_positions(),
        state_snapshot={},
        market=broker,
        broker=broker.name,
        now=datetime(2026, 4, 3, 14, 35),
    )
    exit_outcome = strategy.generate(exit_context)

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].purpose.value == "exit"

