from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from math import log, sqrt
from typing import Any
from urllib.error import HTTPError
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

    def __init__(
        self, api_key: str, api_secret: str, trading_base_url: str, data_base_url: str
    ):
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
    ) -> Any:
        full_url = url
        if params:
            full_url = f"{url}?{urlencode(params, doseq=True)}"
        data = json.dumps(payload).encode() if payload is not None else None
        request = Request(
            full_url, data=data, headers=self._headers(), method=method.upper()
        )
        with urlopen(request) as response:
            return json.loads(response.read().decode())

    @staticmethod
    def _parse_timestamp(raw_value: str | None) -> datetime | None:
        if not raw_value:
            return None
        parsed = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(UTC)
        return parsed.replace(tzinfo=None)

    def get_clock(self) -> MarketClock:
        payload = self._request("GET", f"{self.trading_base_url}/clock")
        return MarketClock(
            timestamp=self._parse_timestamp(payload.get("timestamp"))
            or datetime.now(UTC).replace(tzinfo=None),
            is_open=bool(payload["is_open"]),
            next_open=self._parse_timestamp(payload.get("next_open")),
            next_close=self._parse_timestamp(payload.get("next_close")),
        )

    def get_stock_quote(self, symbol: str) -> Quote:
        try:
            payload = self._request(
                "GET", f"{self.data_base_url}/v2/stocks/{symbol}/snapshot"
            )
        except HTTPError:
            if symbol.upper() == "VIX":
                return self._proxy_vix_quote()
            raise
        latest_trade = payload.get("latestTrade") or {}
        latest_quote = payload.get("latestQuote") or {}
        return Quote(
            bid=float(latest_quote.get("bp") or 0),
            ask=float(latest_quote.get("ap") or 0),
            last=float(latest_trade.get("p") or 0),
            timestamp=self._parse_timestamp(latest_trade.get("t")),
        )

    def _proxy_vix_quote(self, lookback_days: int = 20) -> Quote:
        end_date = date.today()
        start_date = end_date - timedelta(days=max(lookback_days * 3, 30))
        payload = self._request(
            "GET",
            f"{self.data_base_url}/v2/stocks/SPY/bars",
            params={
                "timeframe": "1Day",
                "start": f"{start_date.isoformat()}T00:00:00Z",
                "end": f"{end_date.isoformat()}T23:59:59Z",
                "adjustment": "all",
                "sort": "asc",
                "feed": "iex",
            },
        )
        bars = payload.get("bars") if isinstance(payload, dict) else None
        closes: list[float] = []
        for bar in bars or []:
            if not isinstance(bar, dict):
                continue
            raw_close = bar.get("c")
            if raw_close is None:
                continue
            closes.append(float(raw_close))
        if len(closes) < 2:
            raise ValueError("insufficient bars for proxy VIX estimate")
        log_returns = [
            log(closes[idx] / closes[idx - 1]) for idx in range(1, len(closes))
        ]
        mean_return = sum(log_returns) / len(log_returns)
        variance = sum((value - mean_return) ** 2 for value in log_returns) / len(
            log_returns
        )
        annualized_volatility = max(0.10, min(0.40, sqrt(variance) * sqrt(252.0)))
        proxy_vix = round(annualized_volatility * 100.0, 2)
        return Quote(
            bid=max(proxy_vix - 0.05, 0.0),
            ask=proxy_vix + 0.05,
            last=proxy_vix,
        )

    def get_option_contracts(
        self, underlying: str, expiry: str
    ) -> list[OptionContract]:
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
                    expiry=datetime.strptime(
                        item["expiration_date"], "%Y-%m-%d"
                    ).date(),
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
                timestamp=self._parse_timestamp(quote_payload.get("t")),
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
        items = payload if isinstance(payload, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
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
                    {
                        "symbol": leg.symbol,
                        "side": leg.side.value,
                        "ratio_qty": leg.ratio_qty,
                    }
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
        response = self._request(
            "POST", f"{self.trading_base_url}/orders", payload=payload
        )
        filled_at = self._parse_timestamp(response.get("filled_at"))
        return OrderResult(
            order_id=response["id"],
            intent_id=intent.intent_id,
            strategy_id=intent.strategy_id,
            broker=self.name,
            status=OrderStatus.FILLED
            if response.get("status") == "filled"
            else OrderStatus.ACCEPTED,
            submitted_at=self._parse_timestamp(response["submitted_at"])
            or datetime.now(UTC).replace(tzinfo=None),
            filled_at=filled_at,
            fill_price=float(response["filled_avg_price"])
            if response.get("filled_avg_price")
            else None,
            raw=response,
        )

    def list_orders(self, status: str = "all", limit: int = 200) -> list[BrokerOrder]:
        payload = self._request(
            "GET",
            f"{self.trading_base_url}/orders",
            params={"status": status, "limit": limit, "nested": "true"},
        )
        orders: list[BrokerOrder] = []
        items = payload if isinstance(payload, list) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            legs = [
                OptionLeg(
                    symbol=leg.get("symbol", ""),
                    side=Side(leg.get("side", "buy")),
                    ratio_qty=int(leg.get("ratio_qty", 1) or 1),
                )
                for leg in item.get("legs", []) or []
                if isinstance(leg, dict) and leg.get("symbol")
            ]
            orders.append(
                BrokerOrder(
                    order_id=item["id"],
                    broker=self.name,
                    status=str(item.get("status", "unknown")),
                    symbol=item.get("symbol"),
                    side=item.get("side"),
                    order_type=item.get("type"),
                    quantity=float(item["qty"])
                    if item.get("qty") is not None
                    else None,
                    filled_quantity=(
                        float(item["filled_qty"])
                        if item.get("filled_qty") is not None
                        else None
                    ),
                    limit_price=float(item["limit_price"])
                    if item.get("limit_price")
                    else None,
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
