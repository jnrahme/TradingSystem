from __future__ import annotations

from datetime import datetime

from new_trading_system.adapters.internal_paper import InternalPaperBrokerAdapter, build_demo_snapshot
from new_trading_system.models import (
    AccountSnapshot,
    AssetClass,
    IntentPurpose,
    OptionLeg,
    OrderIntent,
    OrderType,
    Position,
    Side,
    StrategyContext,
    StrategyManifest,
)
from new_trading_system.services.risk_engine import RiskEngine
from new_trading_system.strategies.legacy_iron_condor import LegacyIronCondorStrategy


def _manifest() -> StrategyManifest:
    return StrategyManifest(
        strategy_id="legacy-iron-condor",
        family="options",
        version="1.0.0",
        asset_classes=(AssetClass.OPTION_MULTI_LEG,),
        description="test",
        tags=("liquid-etf-only", "defined-risk-only"),
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


def _entry_intent(symbol: str = "SPY") -> OrderIntent:
    return OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol=symbol,
        side=Side.SELL,
        order_type=OrderType.LIMIT,
        limit_price=1.2,
        max_loss=4000.0,
        expected_credit=1.2,
        legs=[
            OptionLeg(f"{symbol}260501P00615000", Side.BUY),
            OptionLeg(f"{symbol}260501P00625000", Side.SELL),
            OptionLeg(f"{symbol}260501C00685000", Side.SELL),
            OptionLeg(f"{symbol}260501C00695000", Side.BUY),
        ],
        metadata={
            "strategy_type": "iron_condor",
            "defined_risk": True,
            "allowed_underlyings": ["SPY", "SPX", "XSP", "QQQ", "IWM"],
            "dte": 28,
            "min_dte": 21,
            "max_dte": 45,
            "min_credit": 0.5,
        },
    )


def _exit_intent() -> OrderIntent:
    return OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.EXIT,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.BUY,
        order_type=OrderType.MARKET,
        max_loss=0.0,
        legs=[
            OptionLeg("SPY260501P00615000", Side.SELL),
            OptionLeg("SPY260501P00625000", Side.BUY),
            OptionLeg("SPY260501C00685000", Side.BUY),
            OptionLeg("SPY260501C00695000", Side.SELL),
        ],
        metadata={
            "strategy_type": "iron_condor",
            "defined_risk": True,
            "allowed_underlyings": ["SPY", "SPX", "XSP", "QQQ", "IWM"],
        },
    )


def test_risk_engine_rejects_non_paper_mode() -> None:
    engine = RiskEngine()
    intent = _entry_intent()
    intent.broker = "ibkr-live"

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
    intent = _entry_intent()

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


def test_risk_engine_rejects_non_whitelisted_underlying() -> None:
    engine = RiskEngine()
    intent = _entry_intent(symbol="SOFI")

    decision = engine.evaluate(
        manifest=_manifest(),
        account=_account(),
        positions=[],
        intent=intent,
        market_open=True,
        broker_mode="paper-alpaca",
    )

    assert decision.approved is False
    assert any("underlying not allowed" in reason for reason in decision.reasons)


def test_risk_engine_blocks_new_entries_after_daily_loss_limit() -> None:
    engine = RiskEngine()
    account = _account()
    account.metadata["daily_pnl"] = -2500.0

    decision = engine.evaluate(
        manifest=_manifest(),
        account=account,
        positions=[],
        intent=_entry_intent(),
        market_open=True,
        broker_mode="paper-alpaca",
    )

    assert decision.approved is False
    assert any("daily loss limit exceeded" in reason for reason in decision.reasons)


def test_risk_engine_allows_exit_when_entry_guardrails_are_breached() -> None:
    engine = RiskEngine()
    account = _account()
    account.metadata["daily_pnl"] = -5000.0

    decision = engine.evaluate(
        manifest=_manifest(),
        account=account,
        positions=[
            Position(
                symbol="SPY260501P00625000",
                underlying="SPY",
                asset_class=AssetClass.OPTION,
                qty=-1,
                avg_entry_price=2.0,
                current_price=1.0,
                market_value=-100.0,
                unrealized_pl=100.0,
            )
        ],
        intent=_exit_intent(),
        market_open=False,
        broker_mode="paper-alpaca",
        intraday_metrics={"fills_today": 50, "structures_today": 4},
    )

    assert decision.approved is True
    assert any("closing and repair intents stay permitted" in warning for warning in decision.warnings)


def test_risk_engine_rejects_duplicate_option_stacking() -> None:
    engine = RiskEngine()
    positions = [
        Position(
            symbol="SPY260501P00615000",
            underlying="SPY",
            asset_class=AssetClass.OPTION,
            qty=1,
            avg_entry_price=1.0,
            current_price=1.0,
            market_value=100.0,
            unrealized_pl=0.0,
        )
    ]

    decision = engine.evaluate(
        manifest=_manifest(),
        account=_account(),
        positions=positions,
        intent=_entry_intent(),
        market_open=True,
        broker_mode="paper-alpaca",
    )

    assert decision.approved is False
    assert any("position stacking blocked" in reason for reason in decision.reasons)


def test_risk_engine_rejects_cumulative_risk_above_cap() -> None:
    strategy = LegacyIronCondorStrategy()
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    manifest = strategy.manifest()
    account = AccountSnapshot(
        equity=11000.0,
        buying_power=22000.0,
        cash=11000.0,
        currency="USD",
        status="ACTIVE",
        venue="paper",
        mode="paper-alpaca",
    )

    generated = strategy.generate(
        StrategyContext(
            manifest=manifest,
            account=broker.get_account_snapshot(),
            clock=broker.get_clock(),
            positions=[],
            state_snapshot={},
            market=broker,
            broker=broker.name,
            now=datetime(2026, 4, 3, 14, 30),
        )
    )
    broker.submit_order(generated.intents[0])

    next_intent = _entry_intent()
    next_intent.max_loss = 540.0
    next_intent.legs = [
        OptionLeg("SPY260508P00615000", Side.BUY),
        OptionLeg("SPY260508P00625000", Side.SELL),
        OptionLeg("SPY260508C00685000", Side.SELL),
        OptionLeg("SPY260508C00695000", Side.BUY),
    ]
    next_intent.metadata["dte"] = 35

    decision = RiskEngine().evaluate(
        manifest=_manifest(),
        account=account,
        positions=broker.get_positions(),
        intent=next_intent,
        market_open=True,
        broker_mode="paper-alpaca",
    )

    assert decision.approved is False
    assert any("projected open risk" in reason for reason in decision.reasons)


def test_risk_engine_rejects_intraday_structure_limit() -> None:
    engine = RiskEngine()

    decision = engine.evaluate(
        manifest=_manifest(),
        account=_account(),
        positions=[],
        intent=_entry_intent(),
        market_open=True,
        broker_mode="paper-alpaca",
        intraday_metrics={"structures_today": 1, "fills_today": 0},
    )

    assert decision.approved is False
    assert any("max structures guardrail hit" in reason for reason in decision.reasons)
