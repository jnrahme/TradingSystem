from __future__ import annotations

from datetime import datetime

from new_trading_system.adapters.internal_paper import InternalPaperBrokerAdapter, build_demo_snapshot
from new_trading_system.models import StrategyContext
from new_trading_system.strategies.legacy_iron_condor import (
    LegacyIronCondorSettings,
    LegacyIronCondorStrategy,
)


def make_context(
    strategy: LegacyIronCondorStrategy,
    broker: InternalPaperBrokerAdapter,
    now: datetime,
):
    manifest = strategy.manifest()
    return StrategyContext(
        manifest=manifest,
        account=broker.get_account_snapshot(),
        clock=broker.get_clock(),
        positions=broker.get_positions(),
        state_snapshot={},
        market=broker,
        broker=broker.name,
        now=now,
    )


def open_demo_condor(
    strategy: LegacyIronCondorStrategy,
    broker: InternalPaperBrokerAdapter,
    now: datetime,
) -> None:
    entry_outcome = strategy.generate(make_context(strategy, broker, now))
    assert len(entry_outcome.intents) == 1
    broker.submit_order(entry_outcome.intents[0])


def leg_symbols_by_side(broker: InternalPaperBrokerAdapter) -> tuple[list[str], list[str]]:
    short_legs = []
    long_legs = []
    for position in broker.get_positions():
        if position.qty < 0:
            short_legs.append(position.symbol)
        else:
            long_legs.append(position.symbol)
    return short_legs, long_legs


def test_legacy_strategy_generates_exit_when_profit_target_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))
    short_legs, long_legs = leg_symbols_by_side(broker)

    for symbol, quote in broker.snapshot.option_quotes.items():
        if symbol in short_legs:
            quote.bid = 0.95
            quote.ask = 1.05
        elif symbol in long_legs:
            quote.bid = 0.0
            quote.ask = 0.1

    exit_outcome = strategy.generate(make_context(strategy, broker, datetime(2026, 4, 3, 14, 35)))

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].purpose.value == "exit"
    assert exit_outcome.intents[0].metadata["reason"] == "profit_target"
    assert exit_outcome.intents[0].metadata["reason_detail"] == "57.1% profit versus 50% target"


def test_legacy_strategy_generates_exit_when_stop_loss_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))
    short_legs, long_legs = leg_symbols_by_side(broker)

    for symbol, quote in broker.snapshot.option_quotes.items():
        if symbol in short_legs:
            quote.bid = 10.95
            quote.ask = 11.05
        elif symbol in long_legs:
            quote.bid = 0.05
            quote.ask = 0.15

    exit_outcome = strategy.generate(make_context(strategy, broker, datetime(2026, 4, 3, 14, 35)))

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].metadata["reason"] == "stop_loss"


def test_legacy_strategy_generates_exit_when_dte_threshold_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    entry_time = datetime(2026, 4, 3, 14, 30)
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=entry_time))
    open_demo_condor(strategy, broker, entry_time)

    exit_outcome = strategy.generate(make_context(strategy, broker, datetime(2026, 5, 1, 14, 30)))

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].metadata["reason"] == "exit_dte"
    assert exit_outcome.intents[0].metadata["reason_detail"] == "7 DTE remaining"


def test_legacy_strategy_does_not_reopen_same_expiry_when_capacity_remains() -> None:
    strategy = LegacyIronCondorStrategy(
        settings=LegacyIronCondorSettings(max_open_structures=2),
    )
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))

    outcome = strategy.generate(make_context(strategy, broker, datetime(2026, 4, 3, 14, 40)))

    assert outcome.intents == []
    assert outcome.state_snapshot["blocked_entry_reason"] == "entry skipped because expiry 2026-05-08 is already open"


def test_legacy_strategy_flags_incomplete_condor_structures() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))

    first_symbol = next(iter(broker._positions))
    del broker._positions[first_symbol]

    outcome = strategy.generate(make_context(strategy, broker, datetime(2026, 4, 3, 14, 40)))

    assert outcome.intents == []
    assert outcome.state_snapshot["structure_issues"][0]["issue"] == "incomplete_condor"
    assert any(alert.level == "warning" for alert in outcome.alerts)
    assert outcome.state_snapshot["blocked_entry_reason"] == (
        "entry skipped because a non-canonical iron condor structure needs operator review"
    )
