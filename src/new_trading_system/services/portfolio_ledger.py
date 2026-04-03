from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import AccountSnapshot, AssetClass, OrderIntent, OrderResult, Position, json_ready
from ..time_utils import utc_now


@dataclass(slots=True)
class LedgerSummary:
    payload: dict[str, Any]


class PortfolioLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists strategy_runs (
                    run_id integer primary key autoincrement,
                    strategy_id text not null,
                    broker text not null,
                    market_open integer not null,
                    alerts_count integer not null,
                    intents_count integer not null,
                    state_snapshot text not null,
                    created_at text not null
                );

                create table if not exists intents (
                    intent_id text primary key,
                    strategy_id text not null,
                    broker text not null,
                    purpose text not null,
                    asset_class text not null,
                    symbol text not null,
                    payload text not null,
                    created_at text not null
                );

                create table if not exists orders (
                    order_id text primary key,
                    intent_id text not null,
                    strategy_id text not null,
                    broker text not null,
                    status text not null,
                    fill_price real,
                    payload text not null,
                    submitted_at text not null,
                    filled_at text
                );

                create table if not exists positions_latest (
                    broker text not null,
                    symbol text not null,
                    underlying text not null,
                    asset_class text not null,
                    qty real not null,
                    avg_entry_price real not null,
                    current_price real not null,
                    market_value real not null,
                    unrealized_pl real not null,
                    strategy_id text,
                    payload text not null,
                    updated_at text not null,
                    primary key (broker, symbol)
                );

                create table if not exists symbol_strategy_map (
                    symbol text primary key,
                    strategy_id text not null,
                    updated_at text not null
                );
                """
            )

    def record_strategy_run(
        self,
        strategy_id: str,
        broker: str,
        market_open: bool,
        alerts_count: int,
        intents_count: int,
        state_snapshot: dict[str, Any],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert into strategy_runs (
                    strategy_id, broker, market_open, alerts_count, intents_count, state_snapshot, created_at
                ) values (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    strategy_id,
                    broker,
                    int(market_open),
                    alerts_count,
                    intents_count,
                    json.dumps(json_ready(state_snapshot)),
                    utc_now().isoformat(),
                ),
            )

    def record_intent(self, intent: OrderIntent) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into intents (
                    intent_id, strategy_id, broker, purpose, asset_class, symbol, payload, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    intent.intent_id,
                    intent.strategy_id,
                    intent.broker,
                    intent.purpose.value,
                    intent.asset_class.value,
                    intent.symbol,
                    json.dumps(json_ready(intent)),
                    intent.created_at.isoformat(),
                ),
            )

    def record_order_result(self, intent: OrderIntent, result: OrderResult) -> None:
        symbols = [leg.symbol for leg in intent.legs] or [intent.symbol]
        with self._connect() as conn:
            conn.execute(
                """
                insert or replace into orders (
                    order_id, intent_id, strategy_id, broker, status, fill_price, payload, submitted_at, filled_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.order_id,
                    result.intent_id,
                    result.strategy_id,
                    result.broker,
                    result.status.value,
                    result.fill_price,
                    json.dumps(json_ready(result)),
                    result.submitted_at.isoformat(),
                    result.filled_at.isoformat() if result.filled_at else None,
                ),
            )
            now = utc_now().isoformat()
            for symbol in symbols:
                conn.execute(
                    """
                    insert into symbol_strategy_map (symbol, strategy_id, updated_at)
                    values (?, ?, ?)
                    on conflict(symbol) do update set
                      strategy_id=excluded.strategy_id,
                      updated_at=excluded.updated_at
                    """,
                    (symbol, intent.strategy_id, now),
                )

    def replace_positions(self, broker: str, positions: list[Position]) -> None:
        with self._connect() as conn:
            conn.execute("delete from positions_latest where broker = ?", (broker,))
            for position in positions:
                strategy_id = position.strategy_id
                if strategy_id is None:
                    row = conn.execute(
                        "select strategy_id from symbol_strategy_map where symbol = ?",
                        (position.symbol,),
                    ).fetchone()
                    strategy_id = row["strategy_id"] if row else None

                conn.execute(
                    """
                    insert or replace into positions_latest (
                        broker, symbol, underlying, asset_class, qty, avg_entry_price, current_price,
                        market_value, unrealized_pl, strategy_id, payload, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        broker,
                        position.symbol,
                        position.underlying,
                        position.asset_class.value,
                        position.qty,
                        position.avg_entry_price,
                        position.current_price,
                        position.market_value,
                        position.unrealized_pl,
                        strategy_id,
                        json.dumps(json_ready(position)),
                        utc_now().isoformat(),
                    ),
                )

    def get_positions(self, broker: str) -> list[Position]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select symbol, underlying, asset_class, qty, avg_entry_price, current_price,
                       market_value, unrealized_pl, strategy_id, payload
                from positions_latest
                where broker = ?
                order by symbol
                """,
                (broker,),
            ).fetchall()

        positions: list[Position] = []
        for row in rows:
            payload = json.loads(row["payload"]) if row["payload"] else {}
            positions.append(
                Position(
                    symbol=row["symbol"],
                    underlying=row["underlying"],
                    asset_class=AssetClass(row["asset_class"]),
                    qty=float(row["qty"]),
                    avg_entry_price=float(row["avg_entry_price"]),
                    current_price=float(row["current_price"]),
                    market_value=float(row["market_value"]),
                    unrealized_pl=float(row["unrealized_pl"]),
                    strategy_id=row["strategy_id"],
                    metadata=payload.get("metadata", {}) if isinstance(payload, dict) else {},
                )
            )
        return positions

    def get_intraday_metrics(self, broker: str, account: AccountSnapshot) -> dict[str, float | int]:
        today = utc_now().date().isoformat()
        with self._connect() as conn:
            order_counts = conn.execute(
                """
                select
                    coalesce(sum(case when status = 'filled' then 1 else 0 end), 0) as fills_today,
                    coalesce(sum(case when status in ('accepted', 'filled') then 1 else 0 end), 0) as orders_today
                from orders
                where broker = ?
                  and substr(submitted_at, 1, 10) = ?
                """,
                (broker, today),
            ).fetchone()
            structure_counts = conn.execute(
                """
                select count(distinct i.intent_id) as structures_today
                from intents i
                join orders o on o.intent_id = i.intent_id
                where i.broker = ?
                  and i.purpose = 'entry'
                  and i.asset_class = 'option_multi_leg'
                  and o.status in ('accepted', 'filled')
                  and substr(o.submitted_at, 1, 10) = ?
                """,
                (broker, today),
            ).fetchone()

        daily_pnl = 0.0
        if isinstance(account.metadata, dict):
            try:
                daily_pnl = float(account.metadata.get("daily_pnl", 0.0) or 0.0)
            except (TypeError, ValueError):
                daily_pnl = 0.0

        return {
            "daily_pnl": round(daily_pnl, 2),
            "fills_today": int(order_counts["fills_today"] or 0),
            "orders_today": int(order_counts["orders_today"] or 0),
            "structures_today": int(structure_counts["structures_today"] or 0),
        }

    def build_summary(self, account: AccountSnapshot, broker: str) -> LedgerSummary:
        with self._connect() as conn:
            orders = conn.execute(
                """
                select strategy_id, status, count(*) as count
                from orders
                where broker = ?
                group by strategy_id, status
                """,
                (broker,),
            ).fetchall()
            positions = conn.execute(
                """
                select coalesce(strategy_id, 'unassigned') as strategy_id,
                       count(*) as count,
                       coalesce(sum(unrealized_pl), 0) as unrealized_pl,
                       coalesce(sum(market_value), 0) as market_value
                from positions_latest
                where broker = ?
                group by coalesce(strategy_id, 'unassigned')
                """,
                (broker,),
            ).fetchall()
            runs = conn.execute(
                """
                select strategy_id, count(*) as runs
                from strategy_runs
                where broker = ?
                group by strategy_id
                """,
                (broker,),
            ).fetchall()

        order_summary: dict[str, dict[str, int]] = {}
        for row in orders:
            order_summary.setdefault(row["strategy_id"], {})[row["status"]] = row["count"]

        position_summary: dict[str, dict[str, float]] = {}
        for row in positions:
            position_summary[row["strategy_id"]] = {
                "open_positions": row["count"],
                "unrealized_pl": round(row["unrealized_pl"], 2),
                "market_value": round(row["market_value"], 2),
            }

        run_summary = {row["strategy_id"]: row["runs"] for row in runs}
        strategy_ids = sorted(set(order_summary) | set(position_summary) | set(run_summary))

        payload = {
            "generated_at": utc_now().isoformat(),
            "broker": broker,
            "account": json_ready(account),
            "strategies": [
                {
                    "strategy_id": strategy_id,
                    "runs": run_summary.get(strategy_id, 0),
                    "orders": order_summary.get(strategy_id, {}),
                    **position_summary.get(
                        strategy_id,
                        {"open_positions": 0, "unrealized_pl": 0.0, "market_value": 0.0},
                    ),
                }
                for strategy_id in strategy_ids
            ],
        }
        return LedgerSummary(payload=payload)

    def write_summary(self, path: Path, account: AccountSnapshot, broker: str) -> LedgerSummary:
        summary = self.build_summary(account, broker=broker)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary.payload, indent=2))
        return summary
