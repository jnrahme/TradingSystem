from __future__ import annotations

import importlib
from datetime import datetime

models_module = importlib.import_module("new_trading_system.models")
execution_engine_module = importlib.import_module(
    "new_trading_system.services.execution_engine"
)
ledger_module = importlib.import_module("new_trading_system.services.portfolio_ledger")
risk_engine_module = importlib.import_module("new_trading_system.services.risk_engine")
time_utils_module = importlib.import_module("new_trading_system.time_utils")

AccountSnapshot = models_module.AccountSnapshot
AssetClass = models_module.AssetClass
BrokerOrder = models_module.BrokerOrder
IntentPurpose = models_module.IntentPurpose
OptionLeg = models_module.OptionLeg
OrderIntent = models_module.OrderIntent
Side = models_module.Side
StrategyManifest = models_module.StrategyManifest
ExecutionEngine = execution_engine_module.ExecutionEngine
PortfolioLedger = ledger_module.PortfolioLedger
RiskEngine = risk_engine_module.RiskEngine
utc_now = time_utils_module.utc_now


class StubBroker:
    name = "alpaca-paper"
    mode = "paper-alpaca"

    def __init__(self) -> None:
        self.submit_called = False

    def list_orders(self, status: str = "all", limit: int = 200):
        orders = []
        for index in range(8):
            orders.append(
                BrokerOrder(
                    order_id=f"broker-filled-{index}",
                    broker=self.name,
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
                        OptionLeg(f"SPY2605{index + 1:02d}P00615000", Side.BUY),
                        OptionLeg(f"SPY2605{index + 1:02d}P00625000", Side.SELL),
                        OptionLeg(f"SPY2605{index + 1:02d}C00685000", Side.SELL),
                        OptionLeg(f"SPY2605{index + 1:02d}C00695000", Side.BUY),
                    ],
                )
            )
        return orders

    def submit_order(self, intent: OrderIntent):
        self.submit_called = True
        raise AssertionError(
            "submit_order should not be called when daily structure guardrail rejects"
        )

    def get_positions(self):
        return []

    def get_account_snapshot(self):
        return AccountSnapshot(
            100000,
            200000,
            100000,
            "USD",
            "ACTIVE",
            self.name,
            self.mode,
            metadata={"daily_pnl": 0.0},
        )


def test_execution_engine_uses_broker_intraday_history_for_daily_structure_guardrail(
    tmp_path,
) -> None:
    broker = StubBroker()
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    engine = ExecutionEngine(broker=broker, ledger=ledger, risk_engine=RiskEngine())
    manifest = StrategyManifest(
        strategy_id="legacy-iron-condor",
        family="options",
        version="1.0.0",
        asset_classes=(AssetClass.OPTION_MULTI_LEG,),
        description="test",
        tags=("liquid-etf-only",),
    )
    intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
        quantity=1,
        limit_price=2.8,
        max_loss=720.0,
        legs=[
            OptionLeg("SPY260508P00615000", Side.BUY),
            OptionLeg("SPY260508P00625000", Side.SELL),
            OptionLeg("SPY260508C00685000", Side.SELL),
            OptionLeg("SPY260508C00695000", Side.BUY),
        ],
        metadata={
            "strategy_type": "iron_condor",
            "defined_risk": True,
            "allowed_underlyings": ["SPY"],
            "dte": 35,
            "min_dte": 21,
            "max_dte": 52,
            "min_credit": 0.5,
        },
        created_at=datetime.now(),
    )

    results = engine.process(
        manifest=manifest,
        account=broker.get_account_snapshot(),
        positions=[],
        intents=[intent],
        market_open=True,
        dry_run=False,
    )

    assert results[0].status.value == "rejected"
    assert broker.submit_called is False
    assert any(
        "max structures guardrail hit" in reason for reason in results[0].raw["reasons"]
    )
