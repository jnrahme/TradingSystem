from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..broker_sdk import BrokerAdapter
from ..models import (
    AccountSnapshot,
    AssetClass,
    BrokerOrder,
    MarketClock,
    OptionContract,
    OptionLeg,
    OrderIntent,
    OrderResult,
    OrderStatus,
    Position,
    Quote,
    Side,
)
from ..occ import parse_occ_symbol


class AlpacaPaperBrokerAdapter(BrokerAdapter):
    name = "alpaca-paper"
    mode = "paper-alpaca"

    def __init__(self, api_key: str, api_secret: str, trading_base_url: str, data_base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.trading_base_url = trading_base_url.rstrip("/")
        self.data_base_url = data_base_url.rstrip("/")

    def _headers(self) -> dict[str, str]:
        return {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json",
        }

    def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        full_url = url
        if params:
            full_url = f"{url}?{urlencode(params, doseq=True)}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(full_url, data=data, headers=self._headers(), method=method.upper())
        with urlopen(request) as response:
            return json.loads(response.read().decode())

    @staticmethod
    def _parse_timestamp(raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        return datetime.fromisoformat(raw_value.replace("Z", "+00:00")).replace(tzinfo=None)

    def get_clock(self) -> MarketClock:
        payload = self._request("GET", f"{self.trading_base_url}/clock")
        return MarketClock(
            timestamp=datetime.fromisoformat(payload["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None),
            is_open=bool(payload["is_open"]),
            next_open=datetime.fromisoformat(payload["next_open"].replace("Z", "+00:00")).replace(tzinfo=None),
            next_close=datetime.fromisoformat(payload["next_close"].replace("Z", "+00:00")).replace(tzinfo=None),
        )

    def get_stock_quote(self, symbol: str) -> Quote:
        payload = self._request("GET", f"{self.data_base_url}/v2/stocks/{symbol}/snapshot")
        latest_trade = payload.get("latestTrade") or {}
        latest_quote = payload.get("latestQuote") or {}
        return Quote(
            bid=float(latest_quote.get("bp") or 0),
            ask=float(latest_quote.get("ap") or 0),
            last=float(latest_trade.get("p") or 0),
            timestamp=datetime.fromisoformat(latest_trade["t"].replace("Z", "+00:00")).replace(tzinfo=None)
            if latest_trade.get("t")
            else None,
        )

    def get_option_contracts(self, underlying: str, expiry: str) -> list[OptionContract]:
        payload = self._request(
            "GET",
            f"{self.trading_base_url}/options/contracts",
            params={
                "underlying_symbols": underlying,
                "expiration_date": expiry,
                "status": "active",
                "limit": 1000,
            },
        )
        contracts: list[OptionContract] = []
        for item in payload.get("option_contracts", []):
            contracts.append(
                OptionContract(
                    symbol=item["symbol"],
                    underlying=item["underlying_symbol"],
                    expiry=datetime.strptime(item["expiration_date"], "%Y-%m-%d").date(),
                    strike=float(item["strike_price"]),
                    option_type=item["type"],
                    tradable=bool(item.get("tradable", True)),
                    style=item.get("style"),
                )
            )
        return contracts

    def get_option_quotes(self, symbols: list[str]) -> dict[str, Quote]:
        payload = self._request(
            "GET",
            f"{self.data_base_url}/v1beta1/options/quotes/latest",
            params={"symbols": ",".join(symbols)},
        )
        quotes: dict[str, Quote] = {}
        for symbol, quote_payload in payload.get("quotes", {}).items():
            quotes[symbol] = Quote(
                bid=float(quote_payload.get("bp") or 0),
                ask=float(quote_payload.get("ap") or 0),
                last=None,
                timestamp=datetime.fromisoformat(quote_payload["t"].replace("Z", "+00:00")).replace(tzinfo=None)
                if quote_payload.get("t")
                else None,
            )
        return quotes

    def get_account_snapshot(self) -> AccountSnapshot:
        payload = self._request("GET", f"{self.trading_base_url}/account")
        equity = float(payload["equity"])
        last_equity = float(payload.get("last_equity") or payload["equity"])
        return AccountSnapshot(
            equity=equity,
            buying_power=float(payload["buying_power"]),
            cash=float(payload["cash"]),
            currency=payload["currency"],
            status=payload["status"],
            venue=self.name,
            mode=self.mode,
            metadata={
                "daily_pnl": round(equity - last_equity, 2),
                "last_equity": last_equity,
            },
        )

    def get_positions(self) -> list[Position]:
        payload = self._request("GET", f"{self.trading_base_url}/positions")
        positions: list[Position] = []
        for item in payload:
            parsed = parse_occ_symbol(item["symbol"])
            asset_class = AssetClass.OPTION if parsed else AssetClass.EQUITY
            positions.append(
                Position(
                    symbol=item["symbol"],
                    underlying=parsed.underlying if parsed else item["symbol"],
                    asset_class=asset_class,
                    qty=float(item["qty"]),
                    avg_entry_price=float(item["avg_entry_price"]),
                    current_price=float(item["current_price"]),
                    market_value=float(item["market_value"]),
                    unrealized_pl=float(item["unrealized_pl"]),
                )
            )
        return positions

    def preview_payload(self, intent: OrderIntent) -> dict[str, Any]:
        if intent.asset_class is AssetClass.OPTION_MULTI_LEG:
            payload: dict[str, Any] = {
                "qty": str(intent.quantity),
                "order_class": "mleg",
                "type": intent.order_type.value,
                "time_in_force": intent.time_in_force,
                "legs": [
                    {"symbol": leg.symbol, "side": leg.side.value, "ratio_qty": leg.ratio_qty}
                    for leg in intent.legs
                ],
            }
            if intent.limit_price is not None:
                payload["limit_price"] = str(round(intent.limit_price, 2))
            return payload

        payload = {
            "symbol": intent.symbol,
            "side": intent.side.value,
            "qty": str(intent.quantity),
            "type": intent.order_type.value,
            "time_in_force": intent.time_in_force,
        }
        if intent.limit_price is not None:
            payload["limit_price"] = str(round(intent.limit_price, 2))
        return payload

    def submit_order(self, intent: OrderIntent) -> OrderResult:
        payload = self.preview_payload(intent)
        response = self._request("POST", f"{self.trading_base_url}/orders", payload=payload)
        filled_at = self._parse_timestamp(response.get("filled_at"))
        return OrderResult(
            order_id=response["id"],
            intent_id=intent.intent_id,
            strategy_id=intent.strategy_id,
            broker=self.name,
            status=OrderStatus.FILLED if response.get("status") == "filled" else OrderStatus.ACCEPTED,
            submitted_at=self._parse_timestamp(response["submitted_at"]) or datetime.now(UTC).replace(tzinfo=None),
            filled_at=filled_at,
            fill_price=float(response["filled_avg_price"]) if response.get("filled_avg_price") else None,
            raw=response,
        )

    def list_orders(self, status: str = "all", limit: int = 200) -> list[BrokerOrder]:
        payload = self._request(
            "GET",
            f"{self.trading_base_url}/orders",
            params={"status": status, "limit": limit, "nested": "true"},
        )
        orders: list[BrokerOrder] = []
        for item in payload if isinstance(payload, list) else []:
            legs = [
                OptionLeg(
                    symbol=leg.get("symbol", ""),
                    side=Side(leg.get("side", "buy")),
                    ratio_qty=int(leg.get("ratio_qty", 1) or 1),
                )
                for leg in item.get("legs", []) or []
                if leg.get("symbol")
            ]
            orders.append(
                BrokerOrder(
                    order_id=item["id"],
                    broker=self.name,
                    status=str(item.get("status", "unknown")),
                    symbol=item.get("symbol"),
                    side=item.get("side"),
                    order_type=item.get("type"),
                    quantity=float(item["qty"]) if item.get("qty") is not None else None,
                    filled_quantity=(
                        float(item["filled_qty"]) if item.get("filled_qty") is not None else None
                    ),
                    limit_price=float(item["limit_price"]) if item.get("limit_price") else None,
                    created_at=self._parse_timestamp(item.get("created_at"))
                    or self._parse_timestamp(item.get("submitted_at"))
                    or datetime.now(UTC).replace(tzinfo=None),
                    submitted_at=self._parse_timestamp(item.get("submitted_at")),
                    filled_at=self._parse_timestamp(item.get("filled_at")),
                    legs=legs,
                    raw=item,
                )
            )
        return orders

    def cancel_order(self, order_id: str) -> dict[str, str | bool]:
        self._request("DELETE", f"{self.trading_base_url}/orders/{order_id}")
        return {"cancelled": True, "order_id": order_id}
