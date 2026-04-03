from __future__ import annotations

from new_trading_system.adapters.alpaca_paper import AlpacaPaperBrokerAdapter
from new_trading_system.models import AssetClass, IntentPurpose, OptionLeg, OrderIntent, OrderType, Side


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

