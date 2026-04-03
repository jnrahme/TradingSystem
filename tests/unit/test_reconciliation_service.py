from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from new_trading_system.adapters.internal_paper import InternalPaperBrokerAdapter, build_demo_snapshot
from new_trading_system.models import AccountSnapshot, BrokerOrder, Position, StrategyContext
from new_trading_system.services.portfolio_ledger import PortfolioLedger
from new_trading_system.services.reconciliation import ReconciliationService
from new_trading_system.strategies.legacy_iron_condor import LegacyIronCondorStrategy


class FakeBroker:
    name = "alpaca-paper"
    mode = "paper-alpaca"

    def __init__(self, orders: list[BrokerOrder]):
        self._orders = orders
        self.cancelled: list[str] = []

    def get_account_snapshot(self) -> AccountSnapshot:
        return AccountSnapshot(
            equity=100000.0,
            buying_power=200000.0,
            cash=100000.0,
            currency="USD",
            status="ACTIVE",
            venue=self.name,
            mode=self.mode,
        )

    def get_positions(self) -> list[Position]:
        return []

    def list_orders(self, status: str = "all", limit: int = 200) -> list[BrokerOrder]:
        orders = self._orders
        if status == "open":
            orders = [order for order in orders if order.status == "accepted"]
        return orders[:limit]

    def cancel_order(self, order_id: str) -> dict[str, str | bool]:
        self.cancelled.append(order_id)
        self._orders = [
            replace(order, status="canceled") if order.order_id == order_id else order
            for order in self._orders
        ]
        return {"cancelled": True, "order_id": order_id}


def test_reconcile_syncs_broker_positions_into_ledger(tmp_path: Path) -> None:
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")
    broker = InternalPaperBrokerAdapter(snapshot=build_demo_snapshot(now=datetime(2026, 4, 3, 14, 30)))
    strategy = LegacyIronCondorStrategy()
    manifest = strategy.manifest()
    outcome = strategy.generate(
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
    broker.submit_order(outcome.intents[0])

    report = ReconciliationService(broker=broker, ledger=ledger).reconcile(
        summary_path=tmp_path / "summary.json"
    )

    assert report["position_discrepancy_count"] == 4
    assert report["broker_position_count"] == 4
    assert len(ledger.get_positions("internal-paper")) == 4


def test_verify_cancels_stale_orders_when_requested(tmp_path: Path) -> None:
    created_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=120)
    stale = BrokerOrder(
        order_id="order-1",
        broker="alpaca-paper",
        status="accepted",
        symbol="SPY",
        side="sell",
        order_type="limit",
        quantity=1.0,
        filled_quantity=0.0,
        limit_price=1.25,
        created_at=created_at,
        submitted_at=created_at,
    )
    broker = FakeBroker([stale])
    ledger = PortfolioLedger(tmp_path / "state.sqlite3")

    report = ReconciliationService(broker=broker, ledger=ledger).verify(
        stale_order_age_minutes=60,
        cancel_stale=True,
    )

    assert report["ok"] is True
    assert report["stale_orders_before_count"] == 1
    assert report["stale_orders_after_count"] == 0
    assert broker.cancelled == ["order-1"]
