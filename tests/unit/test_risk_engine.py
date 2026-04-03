from __future__ import annotations

from datetime import datetime

from new_trading_system.models import (
    AccountSnapshot,
    AssetClass,
    IntentPurpose,
    MarketClock,
    OrderIntent,
    OrderType,
    Side,
    StrategyManifest,
)
from new_trading_system.services.risk_engine import RiskEngine


def _manifest() -> StrategyManifest:
    return StrategyManifest(
        strategy_id="legacy-iron-condor",
        family="options",
        version="1.0.0",
        asset_classes=(AssetClass.OPTION_MULTI_LEG,),
        description="test",
    )


def _account() -> AccountSnapshot:
    return AccountSnapshot(
        equity=100000.0,
        buying_power=200000.0,
        cash=100000.0,
        currency="USD",
        status="ACTIVE",
        venue="paper",
        mode="paper-alpaca",
    )


def test_risk_engine_rejects_non_paper_mode() -> None:
    engine = RiskEngine()
    intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="ibkr-live",
        symbol="SPY",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        limit_price=1.2,
        max_loss=4000.0,
    )

    decision = engine.evaluate(
        manifest=_manifest(),
        account=_account(),
        positions=[],
        intent=intent,
        market_open=True,
        broker_mode="live",
    )

    assert decision.approved is False
    assert "paper-only strategy" in decision.reasons[0]


def test_risk_engine_rejects_market_closed_entry() -> None:
    engine = RiskEngine()
    intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        limit_price=1.2,
        max_loss=4000.0,
    )

    decision = engine.evaluate(
        manifest=_manifest(),
        account=_account(),
        positions=[],
        intent=intent,
        market_open=False,
        broker_mode="paper-alpaca",
    )

    assert decision.approved is False
    assert "market is closed" in decision.reasons[0]

