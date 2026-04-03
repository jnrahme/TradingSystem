from __future__ import annotations

from typing import Protocol

from .models import AccountSnapshot, MarketClock, OptionContract, OrderIntent, OrderResult, Position, Quote


class MarketGateway(Protocol):
    def get_clock(self) -> MarketClock:
        ...

    def get_stock_quote(self, symbol: str) -> Quote:
        ...

    def get_option_contracts(self, underlying: str, expiry: str) -> list[OptionContract]:
        ...

    def get_option_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        ...


class BrokerAdapter(MarketGateway, Protocol):
    name: str
    mode: str

    def get_account_snapshot(self) -> AccountSnapshot:
        ...

    def get_positions(self) -> list[Position]:
        ...

    def submit_order(self, intent: OrderIntent) -> OrderResult:
        ...

