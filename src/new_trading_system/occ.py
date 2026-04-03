from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
import re

from .models import Position

OCC_PATTERN = re.compile(r"^([A-Z]{1,6})(\d{6})([PC])(\d{8})$")


@dataclass(slots=True)
class ParsedOptionSymbol:
    symbol: str
    underlying: str
    expiry: date
    option_type: str
    strike: float


@dataclass(slots=True)
class CondorSnapshot:
    underlying: str
    expiry: date
    legs: list[Position]
    entry_credit: float
    mark_to_close: float
    unrealized_pl: float
    dte: int


@dataclass(slots=True)
class CondorStructureIssue:
    underlying: str
    expiry: date
    legs: list[Position]
    dte: int
    issue: str


def build_occ_symbol(underlying: str, expiry: date, option_type: str, strike: float) -> str:
    date_part = expiry.strftime("%y%m%d")
    strike_part = f"{int(round(strike * 1000)):08d}"
    return f"{underlying.upper()}{date_part}{option_type.upper()}{strike_part}"


def parse_occ_symbol(symbol: str) -> ParsedOptionSymbol | None:
    match = OCC_PATTERN.match(symbol.upper().strip())
    if not match:
        return None
    underlying, date_part, option_type, strike_part = match.groups()
    expiry = datetime.strptime(date_part, "%y%m%d").date()
    strike = int(strike_part) / 1000.0
    return ParsedOptionSymbol(
        symbol=symbol.upper(),
        underlying=underlying,
        expiry=expiry,
        option_type=option_type,
        strike=strike,
    )


def extract_underlying(symbol: str) -> str:
    parsed = parse_occ_symbol(symbol)
    if parsed is not None:
        return parsed.underlying
    return symbol.strip().upper()


def calculate_target_expiry(
    now: datetime,
    target_dte: int = 30,
    min_dte: int = 21,
    max_dte: int = 45,
) -> date:
    target = now.date() + timedelta(days=target_dte)
    days_until_friday = (4 - target.weekday()) % 7
    expiry = target + timedelta(days=days_until_friday)
    dte = (expiry - now.date()).days
    if dte < min_dte:
        expiry = expiry + timedelta(days=7)
    if (expiry - now.date()).days > max_dte:
        expiry = expiry - timedelta(days=7)
    return expiry


def is_option_symbol(symbol: str) -> bool:
    return parse_occ_symbol(symbol) is not None


def round_to_5(value: float) -> float:
    return round(value / 5.0) * 5.0


def calculate_condor_strikes(price: float, wing_width: float = 10.0) -> dict[str, float]:
    short_put = round_to_5(price * 0.95)
    long_put = short_put - wing_width
    short_call = round_to_5(price * 1.05)
    long_call = short_call + wing_width
    return {
        "long_put": long_put,
        "short_put": short_put,
        "short_call": short_call,
        "long_call": long_call,
    }


def group_condors(positions: list[Position], as_of: date | None = None) -> list[CondorSnapshot]:
    grouped: dict[tuple[str, date], list[Position]] = {}
    today = as_of or date.today()

    for position in positions:
        parsed = parse_occ_symbol(position.symbol)
        if parsed is None:
            continue
        grouped.setdefault((parsed.underlying, parsed.expiry), []).append(position)

    condors: list[CondorSnapshot] = []
    for (underlying, expiry), legs in grouped.items():
        parsed_legs = [parse_occ_symbol(position.symbol) for position in legs]
        if None in parsed_legs or len(legs) != 4:
            continue

        entry_credit = 0.0
        mark_to_close = 0.0
        for leg in legs:
            qty_abs = abs(leg.qty)
            if leg.qty < 0:
                entry_credit += leg.avg_entry_price * qty_abs * 100
                mark_to_close += leg.current_price * qty_abs * 100
            else:
                entry_credit -= leg.avg_entry_price * qty_abs * 100
                mark_to_close -= leg.current_price * qty_abs * 100

        condors.append(
            CondorSnapshot(
                underlying=underlying,
                expiry=expiry,
                legs=legs,
                entry_credit=round(entry_credit, 2),
                mark_to_close=round(mark_to_close, 2),
                unrealized_pl=round(entry_credit - mark_to_close, 2),
                dte=max(0, (expiry - today).days),
            )
        )

    return condors


def find_condor_structure_issues(
    positions: list[Position],
    as_of: date | None = None,
) -> list[CondorStructureIssue]:
    grouped: dict[tuple[str, date], list[Position]] = {}
    today = as_of or date.today()

    for position in positions:
        parsed = parse_occ_symbol(position.symbol)
        if parsed is None:
            continue
        grouped.setdefault((parsed.underlying, parsed.expiry), []).append(position)

    issues: list[CondorStructureIssue] = []
    for (underlying, expiry), legs in sorted(grouped.items()):
        if len(legs) == 4:
            continue
        issues.append(
            CondorStructureIssue(
                underlying=underlying,
                expiry=expiry,
                legs=sorted(legs, key=lambda leg: leg.symbol),
                dte=max(0, (expiry - today).days),
                issue="too_many_legs" if len(legs) > 4 else "incomplete_condor",
            )
        )
    return issues


def estimate_condor_max_loss(condor: CondorSnapshot) -> float:
    put_short = None
    put_long = None
    call_short = None
    call_long = None
    contracts = 1.0

    for leg in condor.legs:
        parsed = parse_occ_symbol(leg.symbol)
        if parsed is None:
            continue
        contracts = max(contracts, abs(leg.qty))
        if parsed.option_type == "P":
            if leg.qty < 0:
                put_short = parsed.strike
            else:
                put_long = parsed.strike
        elif parsed.option_type == "C":
            if leg.qty < 0:
                call_short = parsed.strike
            else:
                call_long = parsed.strike

    widths = []
    if put_short is not None and put_long is not None:
        widths.append(abs(put_short - put_long))
    if call_short is not None and call_long is not None:
        widths.append(abs(call_short - call_long))
    if not widths:
        return 0.0

    widest_width = max(widths)
    return round(max(0.0, widest_width * 100.0 * contracts - condor.entry_credit), 2)
