from __future__ import annotations

from new_trading_system.models import (
    AccountSnapshot,
    AssetClass,
    IntentPurpose,
    OrderIntent,
    OrderResult,
    OrderStatus,
    Side,
)
from new_trading_system.services.portfolio_ledger import PortfolioLedger
from new_trading_system.time_utils import utc_now


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

    account = AccountSnapshot(100000, 200000, 100000, "USD", "ACTIVE", "alpaca-paper", "paper-alpaca")
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
