from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import date, datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from .time_utils import utc_now


class AssetClass(str, Enum):
    EQUITY = "equity"
    OPTION = "option"
    OPTION_MULTI_LEG = "option_multi_leg"


class IntentPurpose(str, Enum):
    ENTRY = "entry"
    EXIT = "exit"
    REPAIR = "repair"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    ACCEPTED = "accepted"
    FILLED = "filled"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass(slots=True)
class Quote:
    bid: float
    ask: float
    last: float | None = None
    timestamp: datetime | None = None

    @property
    def midpoint(self) -> float:
        bid = self.bid if self.bid > 0 else None
        ask = self.ask if self.ask > 0 else None
        if bid is not None and ask is not None:
            return round((bid + ask) / 2, 4)
        if self.last is not None and self.last > 0:
            return round(self.last, 4)
        if bid is not None:
            return round(bid, 4)
        if ask is not None:
            return round(ask, 4)
        return 0.0


@dataclass(slots=True)
class MarketClock:
    timestamp: datetime
    is_open: bool
    next_open: datetime | None = None
    next_close: datetime | None = None


@dataclass(slots=True)
class OptionContract:
    symbol: str
    underlying: str
    expiry: date
    strike: float
    option_type: str
    tradable: bool = True
    style: str | None = None


@dataclass(slots=True)
class AccountSnapshot:
    equity: float
    buying_power: float
    cash: float
    currency: str
    status: str
    venue: str
    mode: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Position:
    symbol: str
    underlying: str
    asset_class: AssetClass
    qty: float
    avg_entry_price: float
    current_price: float
    market_value: float
    unrealized_pl: float
    strategy_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OptionLeg:
    symbol: str
    side: Side
    ratio_qty: int = 1


@dataclass(slots=True)
class StrategyManifest:
    strategy_id: str
    family: str
    version: str
    asset_classes: tuple[AssetClass, ...]
    description: str
    enabled_by_default: bool = False
    paper_only_by_default: bool = True
    requires_manual_live_approval: bool = True
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class OrderIntent:
    strategy_id: str
    purpose: IntentPurpose
    asset_class: AssetClass
    broker: str
    symbol: str
    side: Side
    quantity: int = 1
    order_type: OrderType = OrderType.MARKET
    time_in_force: str = "day"
    limit_price: float | None = None
    max_loss: float | None = None
    expected_credit: float | None = None
    legs: list[OptionLeg] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    intent_id: str = field(default_factory=lambda: uuid4().hex)
    created_at: datetime = field(default_factory=utc_now)


@dataclass(slots=True)
class RiskDecision:
    approved: bool
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)


@dataclass(slots=True)
class OrderResult:
    order_id: str
    intent_id: str
    strategy_id: str
    broker: str
    status: OrderStatus
    submitted_at: datetime
    raw: dict[str, Any] = field(default_factory=dict)
    fill_price: float | None = None
    filled_at: datetime | None = None


@dataclass(slots=True)
class BrokerOrder:
    order_id: str
    broker: str
    status: str
    symbol: str | None
    side: str | None
    order_type: str | None
    quantity: float | None
    filled_quantity: float | None
    limit_price: float | None
    created_at: datetime
    submitted_at: datetime | None = None
    filled_at: datetime | None = None
    legs: list[OptionLeg] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyAlert:
    level: str
    message: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyOutcome:
    intents: list[OrderIntent] = field(default_factory=list)
    alerts: list[StrategyAlert] = field(default_factory=list)
    state_snapshot: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StrategyContext:
    manifest: StrategyManifest
    account: AccountSnapshot
    clock: MarketClock
    positions: list[Position]
    state_snapshot: dict[str, Any]
    market: Any
    broker: Any
    now: datetime = field(default_factory=utc_now)


def json_ready(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if is_dataclass(value):
        return {key: json_ready(val) for key, val in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): json_ready(val) for key, val in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_ready(item) for item in value]
    return value
