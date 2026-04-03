from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from ..broker_sdk import BrokerAdapter
from ..models import (
    AccountSnapshot,
    AssetClass,
    MarketClock,
    OptionContract,
    OrderIntent,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
)
from ..occ import build_occ_symbol, calculate_condor_strikes, calculate_target_expiry, parse_occ_symbol
from ..time_utils import utc_now


@dataclass(slots=True)
class InternalPaperSnapshot:
    clock: MarketClock
    stock_quotes: dict[str, Quote]
    option_contracts: dict[str, list[OptionContract]]
    option_quotes: dict[str, Quote]


@dataclass(slots=True)
class _PaperPosition:
    symbol: str
    underlying: str
    asset_class: AssetClass
    qty: float
    avg_entry_price: float
    strategy_id: str | None
    metadata: dict = field(default_factory=dict)


class InternalPaperBrokerAdapter(BrokerAdapter):
    name = "internal-paper"
    mode = "paper-internal"

    def __init__(self, snapshot: InternalPaperSnapshot, starting_cash: float = 100000.0):
        self.snapshot = snapshot
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self._positions: dict[str, _PaperPosition] = {}

    @classmethod
    def from_state_file(
        cls, snapshot: InternalPaperSnapshot, state_path: Path, starting_cash: float = 100000.0
    ) -> "InternalPaperBrokerAdapter":
        broker = cls(snapshot=snapshot, starting_cash=starting_cash)
        if not state_path.exists():
            return broker

        payload = json.loads(state_path.read_text())
        broker.cash = float(payload.get("cash", starting_cash))
        broker._positions = {
            item["symbol"]: _PaperPosition(
                symbol=item["symbol"],
                underlying=item["underlying"],
                asset_class=AssetClass(item["asset_class"]),
                qty=float(item["qty"]),
                avg_entry_price=float(item["avg_entry_price"]),
                strategy_id=item.get("strategy_id"),
                metadata=item.get("metadata", {}),
            )
            for item in payload.get("positions", [])
        }
        return broker

    def save_state(self, state_path: Path) -> None:
        payload = {
            "cash": self.cash,
            "positions": [
                {
                    **asdict(position),
                    "asset_class": position.asset_class.value,
                }
                for position in self._positions.values()
            ],
        }
        state_path.write_text(json.dumps(payload, indent=2, sort_keys=True))

    def get_clock(self) -> MarketClock:
        return self.snapshot.clock

    def get_stock_quote(self, symbol: str) -> Quote:
        return self.snapshot.stock_quotes[symbol]

    def get_option_contracts(self, underlying: str, expiry: str) -> list[OptionContract]:
        return list(self.snapshot.option_contracts.get(f"{underlying}:{expiry}", []))

    def get_option_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        return {symbol: self.snapshot.option_quotes[symbol] for symbol in symbols}

    def get_account_snapshot(self) -> AccountSnapshot:
        positions = self.get_positions()
        market_value = sum(position.market_value for position in positions)
        equity = round(self.cash + market_value, 2)
        return AccountSnapshot(
            equity=equity,
            buying_power=round(self.cash * 2, 2),
            cash=round(self.cash, 2),
            currency="USD",
            status="ACTIVE",
            venue=self.name,
            mode=self.mode,
            metadata={"daily_pnl": 0.0, "starting_cash": self.starting_cash},
        )

    def _position_current_price(self, position: _PaperPosition) -> float:
        if position.asset_class is AssetClass.EQUITY:
            return self.get_stock_quote(position.symbol).midpoint
        return self.snapshot.option_quotes[position.symbol].midpoint

    def get_positions(self) -> list[Position]:
        rendered: list[Position] = []
        for position in self._positions.values():
            current_price = self._position_current_price(position)
            market_value = round(current_price * position.qty * 100, 2)
            unrealized_pl = round((current_price - position.avg_entry_price) * position.qty * 100, 2)
            if position.asset_class is AssetClass.EQUITY:
                market_value = round(current_price * position.qty, 2)
                unrealized_pl = round((current_price - position.avg_entry_price) * position.qty, 2)
            rendered.append(
                Position(
                    symbol=position.symbol,
                    underlying=position.underlying,
                    asset_class=position.asset_class,
                    qty=position.qty,
                    avg_entry_price=position.avg_entry_price,
                    current_price=current_price,
                    market_value=market_value,
                    unrealized_pl=unrealized_pl,
                    strategy_id=position.strategy_id,
                    metadata=dict(position.metadata),
                )
            )
        return rendered

    def _fill_multileg_price(self, intent: OrderIntent) -> float:
        quotes = self.get_option_quotes([leg.symbol for leg in intent.legs])
        total = 0.0
        for leg in intent.legs:
            leg_quote = quotes[leg.symbol]
            if leg.side.value == "sell":
                total += leg_quote.midpoint * leg.ratio_qty
            else:
                total -= leg_quote.midpoint * leg.ratio_qty
        return round(total, 2)

    def submit_order(self, intent: OrderIntent) -> OrderResult:
        submitted_at = utc_now()
        order_id = f"paper-{uuid4().hex}"

        if intent.asset_class is AssetClass.OPTION_MULTI_LEG:
            fill_price = self._fill_multileg_price(intent)
            total_credit = fill_price * 100 * intent.quantity
            if intent.purpose.value == "entry":
                self.cash += total_credit
                for leg in intent.legs:
                    parsed = parse_occ_symbol(leg.symbol)
                    if parsed is None:
                        continue
                    quote = self.snapshot.option_quotes[leg.symbol].midpoint
                    signed_qty = leg.ratio_qty * intent.quantity * (
                        -1 if leg.side.value == "sell" else 1
                    )
                    self._positions[leg.symbol] = _PaperPosition(
                        symbol=leg.symbol,
                        underlying=parsed.underlying,
                        asset_class=AssetClass.OPTION,
                        qty=signed_qty,
                        avg_entry_price=quote,
                        strategy_id=intent.strategy_id,
                        metadata={"opened_from_intent": intent.intent_id},
                    )
            else:
                self.cash -= total_credit
                for leg in intent.legs:
                    existing = self._positions.get(leg.symbol)
                    if existing is None:
                        continue
                    signed_qty = leg.ratio_qty * intent.quantity * (
                        -1 if leg.side.value == "sell" else 1
                    )
                    new_qty = existing.qty + signed_qty
                    if abs(new_qty) < 1e-9:
                        del self._positions[leg.symbol]
                    else:
                        existing.qty = new_qty
            return OrderResult(
                order_id=order_id,
                intent_id=intent.intent_id,
                strategy_id=intent.strategy_id,
                broker=self.name,
                status=OrderStatus.FILLED,
                submitted_at=submitted_at,
                filled_at=submitted_at,
                fill_price=fill_price,
                raw={"adapter": self.name},
            )

        quote = self.get_stock_quote(intent.symbol).midpoint
        signed_qty = intent.quantity if intent.side.value == "buy" else -intent.quantity
        self.cash -= signed_qty * quote
        self._positions[intent.symbol] = _PaperPosition(
            symbol=intent.symbol,
            underlying=intent.symbol,
            asset_class=AssetClass.EQUITY,
            qty=signed_qty,
            avg_entry_price=quote,
            strategy_id=intent.strategy_id,
        )
        return OrderResult(
            order_id=order_id,
            intent_id=intent.intent_id,
            strategy_id=intent.strategy_id,
            broker=self.name,
            status=OrderStatus.FILLED,
            submitted_at=submitted_at,
            filled_at=submitted_at,
            fill_price=quote,
            raw={"adapter": self.name},
        )


def build_demo_snapshot(now: datetime | None = None, spy_price: float = 650.0) -> InternalPaperSnapshot:
    timestamp = now or utc_now()
    clock = MarketClock(timestamp=timestamp, is_open=True)
    expiry = calculate_target_expiry(timestamp)
    strikes = calculate_condor_strikes(spy_price)

    contracts = []
    option_quotes: dict[str, Quote] = {}
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
            option_quotes[symbol] = Quote(bid=round(mid - 0.05, 2), ask=round(mid + 0.05, 2))

    return InternalPaperSnapshot(
        clock=clock,
        stock_quotes={"SPY": Quote(bid=spy_price - 0.05, ask=spy_price + 0.05, last=spy_price)},
        option_contracts={f"SPY:{expiry.isoformat()}": contracts},
        option_quotes=option_quotes,
    )
