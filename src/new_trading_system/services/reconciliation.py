from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..broker_sdk import BrokerAdapter
from ..models import AccountSnapshot, BrokerOrder, Position
from .portfolio_ledger import PortfolioLedger


def _position_dict(positions: list[Position]) -> dict[str, Position]:
    return {position.symbol: position for position in positions}


def _serialize_position(position: Position | None) -> dict[str, Any] | None:
    if position is None:
        return None
    return {
        "symbol": position.symbol,
        "underlying": position.underlying,
        "asset_class": position.asset_class.value,
        "qty": position.qty,
        "market_value": position.market_value,
        "unrealized_pl": position.unrealized_pl,
    }


def _serialize_order(order: BrokerOrder) -> dict[str, Any]:
    return {
        "order_id": order.order_id,
        "status": order.status,
        "symbol": order.symbol,
        "side": order.side,
        "order_type": order.order_type,
        "quantity": order.quantity,
        "filled_quantity": order.filled_quantity,
        "limit_price": order.limit_price,
        "created_at": order.created_at.isoformat(),
        "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        "filled_at": order.filled_at.isoformat() if order.filled_at else None,
        "legs": [
            {"symbol": leg.symbol, "side": leg.side.value, "ratio_qty": leg.ratio_qty}
            for leg in order.legs
        ],
    }


def compare_positions(
    ledger_positions: list[Position], broker_positions: list[Position]
) -> list[dict[str, Any]]:
    ledger_map = _position_dict(ledger_positions)
    broker_map = _position_dict(broker_positions)
    all_symbols = sorted(set(ledger_map) | set(broker_map))
    discrepancies: list[dict[str, Any]] = []

    for symbol in all_symbols:
        ledger_position = ledger_map.get(symbol)
        broker_position = broker_map.get(symbol)
        if ledger_position is None:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "issue": "missing_in_ledger",
                    "ledger": None,
                    "broker": _serialize_position(broker_position),
                }
            )
            continue
        if broker_position is None:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "issue": "missing_in_broker",
                    "ledger": _serialize_position(ledger_position),
                    "broker": None,
                }
            )
            continue

        if abs(ledger_position.qty - broker_position.qty) > 1e-6:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "issue": "qty_mismatch",
                    "ledger": _serialize_position(ledger_position),
                    "broker": _serialize_position(broker_position),
                }
            )
            continue

        broker_value = broker_position.market_value or 0.0
        ledger_value = ledger_position.market_value or 0.0
        denominator = abs(broker_value) if broker_value else 1.0
        tolerance = max(1.0, denominator * 0.01)
        if abs(ledger_value - broker_value) > tolerance:
            discrepancies.append(
                {
                    "symbol": symbol,
                    "issue": "market_value_mismatch",
                    "ledger": _serialize_position(ledger_position),
                    "broker": _serialize_position(broker_position),
                }
            )

    return discrepancies


def stale_orders(
    orders: list[BrokerOrder], max_age_minutes: int, now: datetime | None = None
) -> list[BrokerOrder]:
    cutoff = (now or datetime.now(UTC).replace(tzinfo=None)) - timedelta(
        minutes=max_age_minutes
    )
    return [
        order
        for order in orders
        if order.status.lower()
        not in {"filled", "canceled", "cancelled", "rejected", "expired"}
        and order.created_at <= cutoff
    ]


@dataclass(slots=True)
class ReconciliationService:
    broker: BrokerAdapter
    ledger: PortfolioLedger
    account_id: str = "default"

    def reconcile(self, summary_path: Path | None = None) -> dict[str, Any]:
        account = self.broker.get_account_snapshot()
        ledger_positions_before = self.ledger.get_positions(self.broker.name)
        broker_positions = self.broker.get_positions()
        position_discrepancies = compare_positions(
            ledger_positions_before, broker_positions
        )
        all_orders = self.broker.list_orders(status="all")
        self.ledger.sync_broker_orders(self.broker.name, all_orders)
        open_orders = self.broker.list_orders(status="open")

        self.ledger.replace_positions(self.broker.name, broker_positions)
        summary = (
            self.ledger.write_summary(
                summary_path,
                account,
                self.broker.name,
                account_id=self.account_id,
            )
            if summary_path
            else self.ledger.build_summary(
                account, self.broker.name, account_id=self.account_id
            )
        )

        return {
            "ok": True,
            "account_id": self.account_id,
            "broker": self.broker.name,
            "account_status": account.status,
            "ledger_position_count_before": len(ledger_positions_before),
            "broker_position_count": len(broker_positions),
            "position_discrepancy_count": len(position_discrepancies),
            "position_discrepancies": position_discrepancies,
            "open_orders_count": len(open_orders),
            "open_orders": [_serialize_order(order) for order in open_orders],
            "summary": summary.payload,
        }

    def verify(
        self,
        stale_order_age_minutes: int = 60,
        cancel_stale: bool = False,
    ) -> dict[str, Any]:
        account = self.broker.get_account_snapshot()
        ledger_positions = self.ledger.get_positions(self.broker.name)
        broker_positions = self.broker.get_positions()
        position_discrepancies = compare_positions(ledger_positions, broker_positions)
        all_orders = self.broker.list_orders(status="all")
        self.ledger.sync_broker_orders(self.broker.name, all_orders)
        self.ledger.replace_positions(self.broker.name, broker_positions)
        open_orders = self.broker.list_orders(status="open")
        stale_before = stale_orders(open_orders, stale_order_age_minutes)
        cancelled: list[dict[str, str | bool]] = []

        if cancel_stale:
            for order in stale_before:
                cancelled.append(self.broker.cancel_order(order.order_id))
            open_orders = self.broker.list_orders(status="open")

        stale_after = stale_orders(open_orders, stale_order_age_minutes)
        ok = (
            account.status.upper() == "ACTIVE"
            and self.broker.mode.startswith("paper")
            and not position_discrepancies
            and not stale_after
        )

        return {
            "ok": ok,
            "account_id": self.account_id,
            "broker": self.broker.name,
            "account_status": account.status,
            "paper_mode": self.broker.mode,
            "ledger_position_count": len(ledger_positions),
            "broker_position_count": len(broker_positions),
            "position_discrepancy_count": len(position_discrepancies),
            "position_discrepancies": position_discrepancies,
            "open_orders_count": len(open_orders),
            "stale_order_age_minutes": stale_order_age_minutes,
            "stale_orders_before_count": len(stale_before),
            "stale_orders_before": [_serialize_order(order) for order in stale_before],
            "cancelled_orders": cancelled,
            "stale_orders_after_count": len(stale_after),
            "stale_orders_after": [_serialize_order(order) for order in stale_after],
            "open_orders": [_serialize_order(order) for order in open_orders],
        }
