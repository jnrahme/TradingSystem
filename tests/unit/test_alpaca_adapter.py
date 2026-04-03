from __future__ import annotations

from new_trading_system.adapters.alpaca_paper import AlpacaPaperBrokerAdapter
from new_trading_system.models import AssetClass, IntentPurpose, OptionLeg, OrderIntent, OrderType, Side


class StubAlpacaAdapter(AlpacaPaperBrokerAdapter):
    def __init__(self, responses):
        super().__init__(
            api_key="key",
            api_secret="secret",
            trading_base_url="https://paper-api.alpaca.markets/v2",
            data_base_url="https://data.alpaca.markets",
        )
        self.responses = responses
        self.calls = []

    def _request(self, method, url, params=None, payload=None):
        self.calls.append((method, url, params, payload))
        return self.responses.pop(0)


def test_alpaca_preview_payload_builds_mleg_order() -> None:
    adapter = AlpacaPaperBrokerAdapter(
        api_key="key",
        api_secret="secret",
        trading_base_url="https://paper-api.alpaca.markets/v2",
        data_base_url="https://data.alpaca.markets",
    )
    intent = OrderIntent(
        strategy_id="legacy-iron-condor",
        purpose=IntentPurpose.ENTRY,
        asset_class=AssetClass.OPTION_MULTI_LEG,
        broker="alpaca-paper",
        symbol="SPY",
        side=Side.SELL,
        quantity=1,
        order_type=OrderType.LIMIT,
        limit_price=2.15,
        legs=[
            OptionLeg("SPY260501P00615000", Side.BUY),
            OptionLeg("SPY260501P00625000", Side.SELL),
            OptionLeg("SPY260501C00685000", Side.SELL),
            OptionLeg("SPY260501C00695000", Side.BUY),
        ],
    )

    payload = adapter.preview_payload(intent)

    assert payload["order_class"] == "mleg"
    assert payload["type"] == "limit"
    assert payload["limit_price"] == "2.15"
    assert len(payload["legs"]) == 4
    assert payload["legs"][1]["side"] == "sell"


def test_alpaca_list_orders_parses_multileg_orders() -> None:
    adapter = StubAlpacaAdapter(
        [
            [
                {
                    "id": "order-1",
                    "status": "accepted",
                    "symbol": "SPY",
                    "side": "sell",
                    "type": "limit",
                    "qty": "1",
                    "filled_qty": "0",
                    "limit_price": "1.95",
                    "created_at": "2026-04-03T14:30:00Z",
                    "submitted_at": "2026-04-03T14:30:01Z",
                    "legs": [
                        {"symbol": "SPY260501P00615000", "side": "buy", "ratio_qty": 1},
                        {"symbol": "SPY260501P00625000", "side": "sell", "ratio_qty": 1},
                    ],
                }
            ]
        ]
    )

    orders = adapter.list_orders(status="open", limit=5)

    assert len(orders) == 1
    assert orders[0].order_id == "order-1"
    assert orders[0].status == "accepted"
    assert orders[0].legs[1].side == "sell"
    assert adapter.calls[0][0] == "GET"
    assert adapter.calls[0][2] == {"status": "open", "limit": 5, "nested": "true"}


def test_alpaca_cancel_order_calls_delete_endpoint() -> None:
    adapter = StubAlpacaAdapter([{}])

    result = adapter.cancel_order("order-99")

    assert result == {"cancelled": True, "order_id": "order-99"}
    assert adapter.calls[0][0] == "DELETE"
    assert adapter.calls[0][1].endswith("/orders/order-99")
