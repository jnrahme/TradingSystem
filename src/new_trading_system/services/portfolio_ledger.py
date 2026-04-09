from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from ..models import (
    AccountSnapshot,
    AssetClass,
    BrokerOrder,
    OptionLeg,
    OrderIntent,
    OrderResult,
    Position,
    Side,
    json_ready,
)
from ..occ import parse_occ_symbol
from ..time_utils import utc_now


def _infer_condor_order_purpose(legs: list[OptionLeg]) -> str | None:
    parsed_legs = [(parse_occ_symbol(leg.symbol), leg.side) for leg in legs]
    if any(parsed is None for parsed, _side in parsed_legs):
        return None
    puts = sorted(
        [
            (parsed, side)
            for parsed, side in parsed_legs
            if parsed and parsed.option_type == "P"
        ],
        key=lambda item: item[0].strike,
    )
    calls = sorted(
        [
            (parsed, side)
            for parsed, side in parsed_legs
            if parsed and parsed.option_type == "C"
        ],
        key=lambda item: item[0].strike,
    )
    if len(puts) != 2 or len(calls) != 2:
        return None

    put_entry = puts[0][1] is Side.BUY and puts[1][1] is Side.SELL
    call_entry = calls[0][1] is Side.SELL and calls[1][1] is Side.BUY
    if put_entry and call_entry:
        return "entry"

    put_exit = puts[0][1] is Side.SELL and puts[1][1] is Side.BUY
    call_exit = calls[0][1] is Side.BUY and calls[1][1] is Side.SELL
    if put_exit and call_exit:
        return "exit"
    return None


def _extract_broker_fill_price(order: BrokerOrder) -> float | None:
    raw = order.raw if isinstance(order.raw, dict) else {}
    raw_fill = raw.get("filled_avg_price")
    candidates = [raw_fill, order.limit_price]
    for candidate in candidates:
        try:
            return float(candidate) if candidate is not None else None
        except (TypeError, ValueError):
            continue
    return None


def _extract_order_expiry(legs: list[OptionLeg]) -> str | None:
    expiries = {
        parsed.expiry.isoformat()
        for leg in legs
        if (parsed := parse_occ_symbol(leg.symbol)) is not None
    }
    if len(expiries) == 1:
        return next(iter(expiries))
    return None


@dataclass(slots=True)
class LedgerSummary:
    payload: dict[str, Any]


BrokerEvidenceBucket = dict[str, int | float | None]


class PortfolioLedger:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _raw_connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
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

    def _connect(self) -> sqlite3.Connection:
        conn = self._raw_connect()
        self._initialize_schema(conn)
        return conn

    def _initialize(self) -> None:
        with self._raw_connect() as conn:
            self._initialize_schema(conn)

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

    def sync_broker_orders(self, broker: str, orders: list[BrokerOrder]) -> None:
        with self._connect() as conn:
            for order in orders:
                fill_price = None
                if isinstance(order.raw, dict):
                    raw_fill = order.raw.get("filled_avg_price")
                    try:
                        fill_price = float(raw_fill) if raw_fill is not None else None
                    except (TypeError, ValueError):
                        fill_price = None
                conn.execute(
                    """
                    update orders
                    set status = ?,
                        fill_price = coalesce(?, fill_price),
                        filled_at = coalesce(?, filled_at),
                        payload = ?
                    where broker = ? and order_id = ?
                    """,
                    (
                        order.status,
                        fill_price,
                        order.filled_at.isoformat() if order.filled_at else None,
                        json.dumps(json_ready(order)),
                        broker,
                        order.order_id,
                    ),
                )

    def backfill_symbol_strategy_map(
        self, strategy_id: str, orders: Sequence[BrokerOrder]
    ) -> None:
        now = utc_now().isoformat()
        with self._connect() as conn:
            for order in orders:
                if order.status.lower() != "filled":
                    continue
                symbols = [leg.symbol for leg in order.legs if leg.symbol]
                for symbol in symbols:
                    conn.execute(
                        """
                        insert into symbol_strategy_map (symbol, strategy_id, updated_at)
                        values (?, ?, ?)
                        on conflict(symbol) do update set
                          strategy_id=excluded.strategy_id,
                          updated_at=excluded.updated_at
                        """,
                        (symbol, strategy_id, now),
                    )

    def build_broker_order_evidence(
        self,
        broker: str,
        orders: Sequence[BrokerOrder],
        fallback_strategy_id: str | None = None,
    ) -> dict[str, BrokerEvidenceBucket]:
        with self._connect() as conn:
            symbol_rows = conn.execute(
                "select symbol, strategy_id from symbol_strategy_map"
            ).fetchall()

        symbol_map = {row["symbol"]: row["strategy_id"] for row in symbol_rows}
        evidence: dict[str, BrokerEvidenceBucket] = {}
        observed_days: dict[str, set[str]] = {}
        open_entries: dict[tuple[str, str], list[float]] = {}
        sorted_orders = sorted(
            orders,
            key=lambda order: order.filled_at or order.submitted_at or order.created_at,
        )
        for order in sorted_orders:
            if (
                order.broker != broker
                or order.status.lower() != "filled"
                or len(order.legs) != 4
            ):
                continue
            strategy_ids = {
                symbol_map.get(leg.symbol)
                for leg in order.legs
                if symbol_map.get(leg.symbol) is not None
            }
            if len(strategy_ids) == 1:
                strategy_id = next(iter(strategy_ids))
            elif not strategy_ids and fallback_strategy_id is not None:
                strategy_id = fallback_strategy_id
            else:
                continue
            if not isinstance(strategy_id, str):
                continue
            purpose = _infer_condor_order_purpose(order.legs)
            if purpose is None:
                continue
            bucket = evidence.setdefault(
                strategy_id,
                {
                    "entry_fills": 0,
                    "exit_fills": 0,
                    "observed_days": 0,
                    "realized_pnl_total": 0.0,
                    "closed_wins": 0,
                    "closed_losses": 0,
                    "closed_flat": 0,
                    "win_rate_pct": None,
                },
            )
            fill_price = _extract_broker_fill_price(order)
            expiry = _extract_order_expiry(order.legs)
            if purpose == "entry":
                bucket["entry_fills"] = int(bucket.get("entry_fills") or 0) + 1
                if fill_price is not None and expiry is not None:
                    credit = -fill_price if fill_price < 0 else fill_price
                    open_entries.setdefault((strategy_id, expiry), []).append(credit)
            else:
                bucket["exit_fills"] = int(bucket.get("exit_fills") or 0) + 1
                if fill_price is not None and expiry is not None:
                    debit = abs(fill_price)
                    matched_entries = open_entries.get((strategy_id, expiry), [])
                    if matched_entries:
                        entry_credit = matched_entries.pop(0)
                        realized_pnl = round((entry_credit - debit) * 100.0, 2)
                        bucket["realized_pnl_total"] = round(
                            float(bucket.get("realized_pnl_total") or 0.0)
                            + realized_pnl,
                            2,
                        )
                        if realized_pnl > 0:
                            bucket["closed_wins"] = (
                                int(bucket.get("closed_wins") or 0) + 1
                            )
                        elif realized_pnl < 0:
                            bucket["closed_losses"] = (
                                int(bucket.get("closed_losses") or 0) + 1
                            )
                        else:
                            bucket["closed_flat"] = (
                                int(bucket.get("closed_flat") or 0) + 1
                            )
            if order.filled_at is not None:
                observed_days.setdefault(strategy_id, set()).add(
                    order.filled_at.date().isoformat()
                )
            elif order.submitted_at is not None:
                observed_days.setdefault(strategy_id, set()).add(
                    order.submitted_at.date().isoformat()
                )

        for strategy_id, days in observed_days.items():
            evidence.setdefault(
                strategy_id,
                {
                    "entry_fills": 0,
                    "exit_fills": 0,
                    "observed_days": 0,
                    "realized_pnl_total": 0.0,
                    "closed_wins": 0,
                    "closed_losses": 0,
                    "closed_flat": 0,
                    "win_rate_pct": None,
                },
            )["observed_days"] = len(days)
        for bucket in evidence.values():
            exit_fills = int(bucket.get("exit_fills") or 0)
            if exit_fills > 0:
                bucket["win_rate_pct"] = round(
                    (int(bucket.get("closed_wins") or 0) / exit_fills) * 100.0,
                    2,
                )
        return evidence

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
                    metadata=payload.get("metadata", {})
                    if isinstance(payload, dict)
                    else {},
                )
            )
        return positions

    def get_intraday_metrics(
        self, broker: str, account: AccountSnapshot
    ) -> dict[str, float | int]:
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

    def merge_broker_intraday_metrics(
        self,
        broker: str,
        account: AccountSnapshot,
        orders: Sequence[BrokerOrder],
    ) -> dict[str, float | int]:
        metrics = self.get_intraday_metrics(broker, account)
        today = utc_now().date().isoformat()
        broker_fills_today = 0
        broker_orders_today = 0
        broker_structures_today = 0
        submitted_statuses = {"accepted", "filled", "new", "partially_filled"}

        for order in orders:
            if order.broker != broker:
                continue
            timestamp = order.submitted_at or order.created_at
            if timestamp.date().isoformat() != today:
                continue
            status = str(order.status).lower()
            if status in submitted_statuses:
                broker_orders_today += 1
                if (
                    len(order.legs) >= 2
                    and _infer_condor_order_purpose(order.legs) == "entry"
                ):
                    broker_structures_today += 1
            if status == "filled":
                broker_fills_today += 1

        metrics["fills_today"] = max(int(metrics["fills_today"]), broker_fills_today)
        metrics["orders_today"] = max(int(metrics["orders_today"]), broker_orders_today)
        metrics["structures_today"] = max(
            int(metrics["structures_today"]),
            broker_structures_today,
        )
        return metrics

    def build_summary(
        self,
        account: AccountSnapshot,
        broker: str,
        account_id: str | None = None,
    ) -> LedgerSummary:
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
            order_summary.setdefault(row["strategy_id"], {})[row["status"]] = row[
                "count"
            ]

        position_summary: dict[str, dict[str, float]] = {}
        for row in positions:
            position_summary[row["strategy_id"]] = {
                "open_positions": row["count"],
                "unrealized_pl": round(row["unrealized_pl"], 2),
                "market_value": round(row["market_value"], 2),
            }

        run_summary = {row["strategy_id"]: row["runs"] for row in runs}
        strategy_ids = sorted(
            set(order_summary) | set(position_summary) | set(run_summary)
        )

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
                        {
                            "open_positions": 0,
                            "unrealized_pl": 0.0,
                            "market_value": 0.0,
                        },
                    ),
                }
                for strategy_id in strategy_ids
            ],
        }
        if account_id is not None:
            payload["account_id"] = account_id
        return LedgerSummary(payload=payload)

    def build_scorecard(
        self,
        account: AccountSnapshot,
        broker: str,
        account_id: str | None = None,
        replay_recorded: bool = False,
    ) -> dict[str, Any]:
        with self._connect() as conn:
            run_rows = conn.execute(
                """
                select strategy_id, market_open, alerts_count, intents_count, created_at
                from strategy_runs
                where broker = ?
                order by created_at
                """,
                (broker,),
            ).fetchall()
            position_rows = conn.execute(
                """
                select coalesce(strategy_id, 'unassigned') as strategy_id,
                       count(*) as open_positions,
                       coalesce(sum(unrealized_pl), 0) as unrealized_pl,
                       coalesce(sum(market_value), 0) as market_value
                from positions_latest
                where broker = ?
                group by coalesce(strategy_id, 'unassigned')
                """,
                (broker,),
            ).fetchall()
            order_rows = conn.execute(
                """
                select i.strategy_id, i.purpose, i.payload as intent_payload,
                       o.status
                from intents i
                left join orders o on o.intent_id = i.intent_id
                where i.broker = ?
                order by i.created_at
                """,
                (broker,),
            ).fetchall()

        strategies: dict[str, dict[str, Any]] = {}

        def _strategy_bucket(strategy_id: str) -> dict[str, Any]:
            return strategies.setdefault(
                strategy_id,
                {
                    "runs": 0,
                    "market_open_runs": 0,
                    "alerts_emitted": 0,
                    "intents_generated": 0,
                    "observed_days": set(),
                    "entry_orders": {},
                    "exit_orders": {},
                    "paper_entry_fills": 0,
                    "paper_exit_fills": 0,
                    "expected_credit_total": 0.0,
                    "expected_credit_count": 0,
                    "declared_max_loss_total": 0.0,
                    "declared_max_loss_count": 0,
                    "estimated_realized_pl": 0.0,
                    "estimated_closed_wins": 0,
                    "estimated_closed_losses": 0,
                    "estimated_closed_flat": 0,
                    "exit_reason_counts": {},
                    "open_positions": 0,
                    "open_unrealized_pl": 0.0,
                    "open_market_value": 0.0,
                },
            )

        def _increment(counter: dict[str, int], key: str) -> None:
            counter[key] = counter.get(key, 0) + 1

        def _as_float_or_none(value: Any) -> float | None:
            try:
                return float(value)
            except (TypeError, ValueError):
                return None

        for row in run_rows:
            bucket = _strategy_bucket(row["strategy_id"])
            bucket["runs"] += 1
            bucket["market_open_runs"] += int(row["market_open"] or 0)
            bucket["alerts_emitted"] += int(row["alerts_count"] or 0)
            bucket["intents_generated"] += int(row["intents_count"] or 0)
            created_at = str(row["created_at"] or "")
            if len(created_at) >= 10:
                bucket["observed_days"].add(created_at[:10])

        for row in position_rows:
            bucket = _strategy_bucket(row["strategy_id"])
            bucket["open_positions"] = int(row["open_positions"] or 0)
            bucket["open_unrealized_pl"] = round(float(row["unrealized_pl"] or 0.0), 2)
            bucket["open_market_value"] = round(float(row["market_value"] or 0.0), 2)

        for row in order_rows:
            bucket = _strategy_bucket(row["strategy_id"])
            purpose = str(row["purpose"] or "unknown")
            status = str(row["status"] or "missing").lower()
            payload = json.loads(row["intent_payload"]) if row["intent_payload"] else {}
            metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}

            if purpose == "entry":
                _increment(bucket["entry_orders"], status)
                if status == "filled":
                    bucket["paper_entry_fills"] += 1
                expected_credit = _as_float_or_none(payload.get("expected_credit"))
                if expected_credit is not None and status in {"accepted", "filled"}:
                    bucket["expected_credit_total"] += expected_credit
                    bucket["expected_credit_count"] += 1
                max_loss = _as_float_or_none(payload.get("max_loss"))
                if max_loss is not None and status in {"accepted", "filled"}:
                    bucket["declared_max_loss_total"] += max_loss
                    bucket["declared_max_loss_count"] += 1
            elif purpose == "exit":
                _increment(bucket["exit_orders"], status)
                if status == "filled":
                    bucket["paper_exit_fills"] += 1
                    estimated_pl = _as_float_or_none(metadata.get("unrealized_pl"))
                    if estimated_pl is not None:
                        bucket["estimated_realized_pl"] += estimated_pl
                        if estimated_pl > 0:
                            bucket["estimated_closed_wins"] += 1
                        elif estimated_pl < 0:
                            bucket["estimated_closed_losses"] += 1
                        else:
                            bucket["estimated_closed_flat"] += 1
                    _increment(
                        bucket["exit_reason_counts"],
                        str(metadata.get("reason") or "unknown"),
                    )

        strategy_payloads: list[dict[str, Any]] = []
        for strategy_id in sorted(strategies):
            bucket = strategies[strategy_id]
            closed_sample = int(bucket["paper_exit_fills"])
            estimated_win_rate_pct = None
            if closed_sample > 0:
                estimated_win_rate_pct = round(
                    (bucket["estimated_closed_wins"] / closed_sample) * 100.0,
                    2,
                )

            blockers: list[str] = []
            if not replay_recorded:
                blockers.append(
                    "replay results are not recorded in the current repo yet"
                )
            if bucket["paper_entry_fills"] == 0:
                blockers.append("no filled paper entries recorded")
            if bucket["paper_exit_fills"] == 0:
                blockers.append("no filled paper exits recorded")

            avg_expected_credit = None
            if bucket["expected_credit_count"]:
                avg_expected_credit = round(
                    bucket["expected_credit_total"] / bucket["expected_credit_count"],
                    2,
                )

            avg_declared_max_loss = None
            if bucket["declared_max_loss_count"]:
                avg_declared_max_loss = round(
                    bucket["declared_max_loss_total"]
                    / bucket["declared_max_loss_count"],
                    2,
                )

            strategy_payloads.append(
                {
                    "strategy_id": strategy_id,
                    "runs": bucket["runs"],
                    "market_open_runs": bucket["market_open_runs"],
                    "observed_days": len(bucket["observed_days"]),
                    "alerts_emitted": bucket["alerts_emitted"],
                    "intents_generated": bucket["intents_generated"],
                    "entry_orders": bucket["entry_orders"],
                    "exit_orders": bucket["exit_orders"],
                    "paper_entry_fills": bucket["paper_entry_fills"],
                    "paper_exit_fills": bucket["paper_exit_fills"],
                    "avg_expected_credit": avg_expected_credit,
                    "avg_declared_max_loss": avg_declared_max_loss,
                    "open_positions": bucket["open_positions"],
                    "open_unrealized_pl": bucket["open_unrealized_pl"],
                    "open_market_value": bucket["open_market_value"],
                    "estimated_realized_pl_from_filled_exits": round(
                        bucket["estimated_realized_pl"],
                        2,
                    ),
                    "estimated_closed_wins": bucket["estimated_closed_wins"],
                    "estimated_closed_losses": bucket["estimated_closed_losses"],
                    "estimated_closed_flat": bucket["estimated_closed_flat"],
                    "estimated_win_rate_pct": estimated_win_rate_pct,
                    "exit_reason_counts": bucket["exit_reason_counts"],
                    "readiness": {
                        "paper_execution_observed": bucket["paper_entry_fills"] > 0,
                        "paper_exit_observed": bucket["paper_exit_fills"] > 0,
                        "replay_recorded": replay_recorded,
                        "eligible_for_live_consideration": False,
                    },
                    "blockers": blockers,
                }
            )

        payload = {
            "generated_at": utc_now().isoformat(),
            "broker": broker,
            "account": json_ready(account),
            "strategies": strategy_payloads,
        }
        if account_id is not None:
            payload["account_id"] = account_id
        return payload

    def write_summary(
        self,
        path: Path,
        account: AccountSnapshot,
        broker: str,
        account_id: str | None = None,
    ) -> LedgerSummary:
        summary = self.build_summary(account, broker=broker, account_id=account_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(summary.payload, indent=2))
        return summary
