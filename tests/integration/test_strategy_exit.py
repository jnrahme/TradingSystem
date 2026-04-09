from __future__ import annotations

import importlib
from datetime import date, datetime

internal_paper_module = importlib.import_module(
    "new_trading_system.adapters.internal_paper"
)
models_module = importlib.import_module("new_trading_system.models")
occ_module = importlib.import_module("new_trading_system.occ")
strategy_module = importlib.import_module(
    "new_trading_system.strategies.legacy_iron_condor"
)

InternalPaperBrokerAdapter = internal_paper_module.InternalPaperBrokerAdapter
build_demo_snapshot = internal_paper_module.build_demo_snapshot
build_modeled_snapshot = internal_paper_module.build_modeled_snapshot
OptionContract = models_module.OptionContract
Quote = models_module.Quote
StrategyContext = models_module.StrategyContext
build_occ_symbol = occ_module.build_occ_symbol
calculate_condor_strikes = occ_module.calculate_condor_strikes
LegacyIronCondorSettings = strategy_module.LegacyIronCondorSettings
LegacyIronCondorStrategy = strategy_module.LegacyIronCondorStrategy


def make_context(
    strategy,
    broker,
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
    strategy,
    broker,
    now: datetime,
) -> None:
    entry_outcome = strategy.generate(make_context(strategy, broker, now))
    assert len(entry_outcome.intents) == 1
    broker.submit_order(entry_outcome.intents[0])


def leg_symbols_by_side(
    broker,
) -> tuple[list[str], list[str]]:
    short_legs = []
    long_legs = []
    for position in broker.get_positions():
        if position.qty < 0:
            short_legs.append(position.symbol)
        else:
            long_legs.append(position.symbol)
    return short_legs, long_legs


def add_demo_expiry(
    broker,
    expiry: date,
    spy_price: float = 650.0,
) -> None:
    strikes = calculate_condor_strikes(spy_price)
    contracts: list[OptionContract] = []
    price_map = {
        strikes["long_put"]: 5.10,
        strikes["short_put"]: 7.10,
        strikes["short_call"]: 7.35,
        strikes["long_call"]: 5.15,
    }
    for option_type, strike_list in {
        "put": [strikes["long_put"], strikes["short_put"]],
        "call": [strikes["short_call"], strikes["long_call"]],
    }.items():
        for strike in strike_list:
            symbol = build_occ_symbol(
                "SPY",
                expiry,
                "P" if option_type == "put" else "C",
                strike,
            )
            contracts.append(
                OptionContract(
                    symbol=symbol,
                    underlying="SPY",
                    expiry=expiry,
                    strike=strike,
                    option_type=option_type,
                )
            )
            mid = price_map[strike]
            broker.snapshot.option_quotes[symbol] = Quote(
                bid=round(mid - 0.05, 2),
                ask=round(mid + 0.05, 2),
            )

    broker.snapshot.option_contracts[f"SPY:{expiry.isoformat()}"] = contracts


def test_legacy_strategy_generates_exit_when_profit_target_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))
    short_legs, long_legs = leg_symbols_by_side(broker)

    for symbol, quote in broker.snapshot.option_quotes.items():
        if symbol in short_legs:
            quote.bid = 0.95
            quote.ask = 1.05
        elif symbol in long_legs:
            quote.bid = 0.0
            quote.ask = 0.1

    exit_outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 35))
    )

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].purpose.value == "exit"
    assert exit_outcome.intents[0].metadata["reason"] == "profit_target"
    assert exit_outcome.intents[0].order_type.value == "limit"
    assert exit_outcome.intents[0].limit_price is not None
    assert (
        exit_outcome.intents[0].limit_price
        == exit_outcome.intents[0].metadata["target_limit"]
    )
    assert exit_outcome.intents[0].limit_price == round(
        exit_outcome.intents[0].metadata["mark_to_close"] / 100 * 1.03,
        2,
    )
    assert (
        exit_outcome.intents[0].metadata["reason_detail"]
        == "57.1% profit versus 2.5% target"
    )
    broker.submit_order(exit_outcome.intents[0])

    account = broker.get_account_snapshot()
    assert broker.get_positions() == []
    assert account.cash == 100240.0
    assert account.equity == 100240.0
    assert account.buying_power == 200480.0


def test_legacy_strategy_generates_exit_when_stop_loss_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))
    short_legs, long_legs = leg_symbols_by_side(broker)

    for symbol, quote in broker.snapshot.option_quotes.items():
        if symbol in short_legs:
            quote.bid = 10.95
            quote.ask = 11.05
        elif symbol in long_legs:
            quote.bid = 0.05
            quote.ask = 0.15

    exit_outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 35))
    )

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].metadata["reason"] == "stop_loss"
    assert exit_outcome.intents[0].order_type.value == "limit"
    assert exit_outcome.intents[0].limit_price is not None
    assert (
        exit_outcome.intents[0].limit_price
        == exit_outcome.intents[0].metadata["target_limit"]
    )
    assert exit_outcome.intents[0].limit_price == round(
        exit_outcome.intents[0].metadata["mark_to_close"] / 100 * 1.03,
        2,
    )
    broker.submit_order(exit_outcome.intents[0])

    account = broker.get_account_snapshot()
    assert broker.get_positions() == []
    assert account.cash == 98240.0
    assert account.equity == 98240.0
    assert account.buying_power == 196480.0


def test_legacy_strategy_generates_exit_when_dte_threshold_is_hit() -> None:
    strategy = LegacyIronCondorStrategy()
    entry_time = datetime(2026, 4, 3, 14, 30)
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=entry_time))
    open_demo_condor(strategy, broker, entry_time)

    exit_outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 5, 1, 14, 30))
    )

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].metadata["reason"] == "exit_dte"
    assert exit_outcome.intents[0].order_type.value == "limit"
    assert exit_outcome.intents[0].limit_price is not None
    assert (
        exit_outcome.intents[0].limit_price
        == exit_outcome.intents[0].metadata["target_limit"]
    )
    assert exit_outcome.intents[0].limit_price == round(
        exit_outcome.intents[0].metadata["mark_to_close"] / 100 * 1.03,
        2,
    )
    assert exit_outcome.intents[0].metadata["reason_detail"] == "7 DTE remaining"
    broker.submit_order(exit_outcome.intents[0])

    account = broker.get_account_snapshot()
    assert broker.get_positions() == []
    assert account.cash == 100000.0
    assert account.equity == 100000.0
    assert account.buying_power == 200000.0


def test_legacy_strategy_does_not_reopen_same_expiry_when_capacity_remains() -> None:
    strategy = LegacyIronCondorStrategy(
        settings=LegacyIronCondorSettings(max_open_structures=2),
    )
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 40))
    )

    assert outcome.intents == []
    assert (
        outcome.state_snapshot["blocked_entry_reason"]
        == "entry skipped because expiry 2026-05-08 is already open"
    )


def test_legacy_strategy_flags_incomplete_condor_structures() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))

    first_symbol = next(iter(broker._positions))
    del broker._positions[first_symbol]

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 40))
    )

    assert outcome.intents == []
    assert outcome.state_snapshot["structure_issues"][0]["issue"] == "incomplete_condor"
    assert any(alert.level == "warning" for alert in outcome.alerts)
    assert outcome.state_snapshot["blocked_entry_reason"] == (
        "entry skipped because a non-canonical iron condor structure needs operator review"
    )


def test_legacy_strategy_uses_next_available_expiry_when_current_one_is_open() -> None:
    strategy = LegacyIronCondorStrategy(
        settings=LegacyIronCondorSettings(max_open_structures=2),
    )
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    add_demo_expiry(broker, expiry=date(2026, 5, 15))
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 40))
    )

    assert len(outcome.intents) == 1
    assert outcome.intents[0].purpose.value == "entry"
    assert outcome.intents[0].metadata["expiry"] == "2026-05-15"
    assert outcome.state_snapshot["blocked_entry_reason"] is None


def test_legacy_strategy_skips_vix_gate_when_max_open_condors_reached() -> None:
    strategy = LegacyIronCondorStrategy(
        settings=LegacyIronCondorSettings(max_open_structures=1),
    )
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    open_demo_condor(strategy, broker, datetime(2026, 4, 3, 14, 30))
    del broker.snapshot.stock_quotes["VIX"]

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 40))
    )

    assert outcome.intents == []
    assert outcome.state_snapshot["blocked_entry_reason"] == (
        "entry skipped because max open condors is already reached (1/1)"
    )
    assert outcome.state_snapshot["vix_gate_note"] is None


def test_legacy_strategy_never_considers_entry_expiries_inside_exit_dte_window() -> (
    None
):
    strategy = LegacyIronCondorStrategy(
        settings=LegacyIronCondorSettings(min_dte=3, exit_dte=10),
    )

    candidates = strategy._candidate_expiries(date(2026, 4, 7))

    assert candidates
    assert all(days_out > 10 for _expiry, days_out in candidates)
    assert candidates[0][1] == 31


def test_legacy_strategy_blocks_entry_when_vix_is_too_low() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    broker.snapshot.stock_quotes["VIX"] = Quote(bid=9.95, ask=10.05, last=10.0)

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 30))
    )

    assert outcome.intents == []
    assert outcome.state_snapshot["blocked_entry_reason"] == (
        "entry skipped because VIX 10.00 is below minimum 12.00"
    )


def test_legacy_strategy_warns_but_allows_entry_when_vix_quote_is_unavailable() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30))
    )
    del broker.snapshot.stock_quotes["VIX"]

    outcome = strategy.generate(
        make_context(strategy, broker, datetime(2026, 4, 3, 14, 30))
    )

    assert len(outcome.intents) == 1
    assert outcome.state_snapshot["blocked_entry_reason"] is None
    assert outcome.state_snapshot["vix_level"] is None
    assert outcome.state_snapshot["vix_gate_note"] is not None


def test_modeled_snapshot_supports_exit_from_persisted_internal_paper_state(
    tmp_path,
) -> None:
    strategy = LegacyIronCondorStrategy()
    entry_time = datetime(2026, 4, 3, 14, 30)
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=entry_time))
    open_demo_condor(strategy, broker, entry_time)
    state_path = tmp_path / "internal-paper-state.json"
    broker.save_state(state_path)

    modeled_broker = InternalPaperBrokerAdapter.from_state_file(
        snapshot=build_modeled_snapshot(
            now=datetime(2026, 5, 1, 14, 30),
            spy_price=650.0,
            vix_level=18.0,
            existing_option_symbols=[
                position.symbol for position in broker.get_positions()
            ],
        ),
        state_path=state_path,
    )

    exit_outcome = strategy.generate(
        make_context(strategy, modeled_broker, datetime(2026, 5, 1, 14, 30))
    )

    assert len(exit_outcome.intents) == 1
    assert exit_outcome.intents[0].metadata["reason"] == "exit_dte"
