from __future__ import annotations

from datetime import date

from new_trading_system.models import AssetClass, Position
from new_trading_system.occ import build_occ_symbol, group_condors, parse_occ_symbol


def test_build_and_parse_occ_symbol_round_trip() -> None:
    symbol = build_occ_symbol("SPY", date(2026, 5, 1), "P", 635.0)
    parsed = parse_occ_symbol(symbol)

    assert symbol == "SPY260501P00635000"
    assert parsed is not None
    assert parsed.underlying == "SPY"
    assert parsed.expiry == date(2026, 5, 1)
    assert parsed.option_type == "P"
    assert parsed.strike == 635.0


def test_group_condors_calculates_entry_credit_and_pnl() -> None:
    positions = [
        Position("SPY260501P00615000", "SPY", AssetClass.OPTION, 1, 5.0, 2.0, 200.0, -300.0),
        Position("SPY260501P00625000", "SPY", AssetClass.OPTION, -1, 7.0, 3.0, -300.0, 400.0),
        Position("SPY260501C00685000", "SPY", AssetClass.OPTION, -1, 7.0, 3.0, -300.0, 400.0),
        Position("SPY260501C00695000", "SPY", AssetClass.OPTION, 1, 5.0, 2.0, 200.0, -300.0),
    ]

    condors = group_condors(positions, as_of=date(2026, 4, 3))

    assert len(condors) == 1
    assert condors[0].entry_credit == 400.0
    assert condors[0].mark_to_close == 200.0
    assert condors[0].unrealized_pl == 200.0
    assert condors[0].dte == 28

