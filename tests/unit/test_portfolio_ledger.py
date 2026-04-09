from __future__ import annotations

import importlib

models_module = importlib.import_module("new_trading_system.models")
ledger_module = importlib.import_module("new_trading_system.services.portfolio_ledger")
time_utils_module = importlib.import_module("new_trading_system.time_utils")

AccountSnapshot = models_module.AccountSnapshot
AssetClass = models_module.AssetClass
BrokerOrder = models_module.BrokerOrder
IntentPurpose = models_module.IntentPurpose
OptionLeg = models_module.OptionLeg
OrderIntent = models_module.OrderIntent
OrderResult = models_module.OrderResult
OrderStatus = models_module.OrderStatus
Side = models_module.Side
PortfolioLedger = ledger_module.PortfolioLedger
utc_now = time_utils_module.utc_now


def test_ledger_summary_is_scoped_by_broker(tmp_path) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    intent_internal = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="internal-paper",
        symbol="SPY",
        side=Side.SELL,
    )
    intent_alpaca = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
    )
    ledger.record_intent(intent_internal)
    ledger.record_intent(intent_alpaca)
    ledger.record_order_result(
        intent_internal,
        OrderResult(
            order_id="internal-1",
            intent_id=intent_internal.intent_id,
            strategy_id=intent_internal.strategy_id,
            broker="internal-paper",
            status=OrderStatus.FILLED,
            submitted_at=utc_now(),
        ),
    )
    ledger.record_order_result(
        intent_alpaca,
        OrderResult(
            order_id="alpaca-1",
            intent_id=intent_alpaca.intent_id,
            strategy_id=intent_alpaca.strategy_id,
            broker="alpaca-paper",
            status=OrderStatus.SKIPPED,
            submitted_at=utc_now(),
        ),
    )

    account = AccountSnapshot(
        100000, 200000, 100000, "USD", "ACTIVE", "alpaca-paper", "paper-alpaca"
    )
    summary = ledger.build_summary(account, broker="alpaca-paper")

    assert summary.payload["broker"] == "alpaca-paper"
    assert summary.payload["strategies"][0]["orders"] == {"skipped": 1}


def test_ledger_intraday_metrics_count_only_executed_orders(tmp_path) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    live_intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
    )
    skipped_intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
    )

    ledger.record_intent(live_intent)
    ledger.record_intent(skipped_intent)
    ledger.record_order_result(
        live_intent,
        OrderResult(
            order_id="alpaca-filled-1",
            intent_id=live_intent.intent_id,
            strategy_id=live_intent.strategy_id,
            broker="alpaca-paper",
            status=OrderStatus.FILLED,
            submitted_at=utc_now(),
        ),
    )
    ledger.record_order_result(
        skipped_intent,
        OrderResult(
            order_id="alpaca-skipped-1",
            intent_id=skipped_intent.intent_id,
            strategy_id=skipped_intent.strategy_id,
            broker="alpaca-paper",
            status=OrderStatus.SKIPPED,
            submitted_at=utc_now(),
        ),
    )

    metrics = ledger.get_intraday_metrics(
        "alpaca-paper",
        AccountSnapshot(
            100000,
            200000,
            100000,
            "USD",
            "ACTIVE",
            "alpaca-paper",
            "paper-alpaca",
            metadata={"daily_pnl": -125.5},
        ),
    )

    assert metrics == {
        "daily_pnl": -125.5,
        "fills_today": 1,
        "orders_today": 1,
        "structures_today": 1,
    }


def test_ledger_merge_broker_intraday_metrics_uses_broker_history_when_local_db_is_thin(
    tmp_path,
) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    account = AccountSnapshot(
        100000,
        200000,
        100000,
        "USD",
        "ACTIVE",
        "alpaca-paper",
        "paper-alpaca",
        metadata={"daily_pnl": -12.5},
    )
    broker_order = BrokerOrder(
        order_id="broker-1",
        broker="alpaca-paper",
        status="filled",
        symbol=None,
        side=None,
        order_type="limit",
        quantity=1,
        filled_quantity=1,
        limit_price=2.8,
        created_at=utc_now(),
        submitted_at=utc_now(),
        filled_at=utc_now(),
        legs=[
            OptionLeg("SPY260501P00615000", Side.BUY),
            OptionLeg("SPY260501P00625000", Side.SELL),
            OptionLeg("SPY260501C00685000", Side.SELL),
            OptionLeg("SPY260501C00695000", Side.BUY),
        ],
    )

    metrics = ledger.merge_broker_intraday_metrics(
        "alpaca-paper",
        account,
        [broker_order],
    )

    assert metrics == {
        "daily_pnl": -12.5,
        "fills_today": 1,
        "orders_today": 1,
        "structures_today": 1,
    }


def test_ledger_build_broker_order_evidence_computes_realized_pnl_from_entry_exit_pair(
    tmp_path,
) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    ledger.backfill_symbol_strategy_map(
        "legacy-iron-condor",
        [
            BrokerOrder(
                order_id="entry-1",
                broker="alpaca-paper",
                status="filled",
                symbol=None,
                side=None,
                order_type="limit",
                quantity=1,
                filled_quantity=1,
                limit_price=0.46,
                created_at=utc_now(),
                submitted_at=utc_now(),
                filled_at=utc_now(),
                legs=[
                    OptionLeg("SPY260410P00610000", Side.BUY),
                    OptionLeg("SPY260410P00620000", Side.SELL),
                    OptionLeg("SPY260410C00685000", Side.SELL),
                    OptionLeg("SPY260410C00695000", Side.BUY),
                ],
                raw={"filled_avg_price": "-0.45"},
            )
        ],
    )
    evidence = ledger.build_broker_order_evidence(
        "alpaca-paper",
        [
            BrokerOrder(
                order_id="entry-1",
                broker="alpaca-paper",
                status="filled",
                symbol=None,
                side=None,
                order_type="limit",
                quantity=1,
                filled_quantity=1,
                limit_price=0.46,
                created_at=utc_now(),
                submitted_at=utc_now(),
                filled_at=utc_now(),
                legs=[
                    OptionLeg("SPY260410P00610000", Side.BUY),
                    OptionLeg("SPY260410P00620000", Side.SELL),
                    OptionLeg("SPY260410C00685000", Side.SELL),
                    OptionLeg("SPY260410C00695000", Side.BUY),
                ],
                raw={"filled_avg_price": "-0.45"},
            ),
            BrokerOrder(
                order_id="exit-1",
                broker="alpaca-paper",
                status="filled",
                symbol=None,
                side=None,
                order_type="market",
                quantity=1,
                filled_quantity=1,
                limit_price=None,
                created_at=utc_now(),
                submitted_at=utc_now(),
                filled_at=utc_now(),
                legs=[
                    OptionLeg("SPY260410C00685000", Side.BUY),
                    OptionLeg("SPY260410C00695000", Side.SELL),
                    OptionLeg("SPY260410P00610000", Side.SELL),
                    OptionLeg("SPY260410P00620000", Side.BUY),
                ],
                raw={"filled_avg_price": "0.52"},
            ),
        ],
        fallback_strategy_id="legacy-iron-condor",
    )

    assert evidence["legacy-iron-condor"]["entry_fills"] == 1
    assert evidence["legacy-iron-condor"]["exit_fills"] == 1
    assert evidence["legacy-iron-condor"]["realized_pnl_total"] == -7.0
    assert evidence["legacy-iron-condor"]["closed_losses"] == 1
    assert evidence["legacy-iron-condor"]["win_rate_pct"] == 0.0


def test_ledger_summary_can_include_runtime_account_id(tmp_path) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")

    summary = ledger.build_summary(
        AccountSnapshot(
            100000, 200000, 100000, "USD", "ACTIVE", "internal-paper", "paper-internal"
        ),
        broker="internal-paper",
        account_id="primary",
    )

    assert summary.payload["account_id"] == "primary"


def test_ledger_scorecard_reports_paper_evidence_and_blockers(tmp_path) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    ledger.record_strategy_run(
        strategy_id="legacy-iron-condor",
        broker="internal-paper",
        market_open=True,
        alerts_count=1,
        intents_count=1,
        state_snapshot={"generated_intents": 1},
    )
    entry_intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="internal-paper",
        symbol="SPY",
        side=Side.SELL,
        expected_credit=2.1,
        max_loss=790.0,
    )
    exit_intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.EXIT,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="internal-paper",
        symbol="SPY",
        side=Side.BUY,
        metadata={"reason": "profit_target", "unrealized_pl": 125.0},
    )

    ledger.record_intent(entry_intent)
    ledger.record_order_result(
        entry_intent,
        OrderResult(
            order_id="entry-1",
            intent_id=entry_intent.intent_id,
            strategy_id=entry_intent.strategy_id,
            broker="internal-paper",
            status=OrderStatus.FILLED,
            submitted_at=utc_now(),
        ),
    )
    ledger.record_intent(exit_intent)
    ledger.record_order_result(
        exit_intent,
        OrderResult(
            order_id="exit-1",
            intent_id=exit_intent.intent_id,
            strategy_id=exit_intent.strategy_id,
            broker="internal-paper",
            status=OrderStatus.FILLED,
            submitted_at=utc_now(),
        ),
    )

    scorecard = ledger.build_scorecard(
        AccountSnapshot(
            100000,
            200000,
            100000,
            "USD",
            "ACTIVE",
            "internal-paper",
            "paper-internal",
        ),
        broker="internal-paper",
        account_id="primary",
    )

    assert scorecard["account_id"] == "primary"
    strategy = scorecard["strategies"][0]
    assert strategy["paper_entry_fills"] == 1
    assert strategy["paper_exit_fills"] == 1
    assert strategy["avg_expected_credit"] == 2.1
    assert strategy["avg_declared_max_loss"] == 790.0
    assert strategy["estimated_realized_pl_from_filled_exits"] == 125.0
    assert strategy["estimated_win_rate_pct"] == 100.0
    assert strategy["exit_reason_counts"] == {"profit_target": 1}
    assert strategy["readiness"]["paper_execution_observed"] is True
    assert strategy["readiness"]["eligible_for_live_consideration"] is False
    assert (
        "replay results are not recorded in the current repo yet"
        in strategy["blockers"]
    )
