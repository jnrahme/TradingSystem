from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from math import erf, exp, log, sqrt
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ..occ import calculate_condor_strikes, calculate_target_expiry
from ..strategies.legacy_iron_condor import LegacyIronCondorSettings
from ..time_utils import utc_now


@dataclass(slots=True)
class HistoricalBar:
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(slots=True)
class HistoricalBacktestConfig:
    underlying_symbol: str = "SPY"
    target_dte: int = 30
    min_dte: int = 11
    max_dte: int = 52
    wing_width: float = 10.0
    min_credit: float = 0.40
    take_profit_pct: float = 0.025
    stop_loss_pct: float = 1.00
    exit_dte: int = 10
    min_vix: float = 12.0
    max_vix: float = 35.0
    risk_free_rate: float = 0.05
    slippage_pct: float = 0.075
    iv_lookback_days: int = 20
    entry_spacing_trading_days: int = 5
    max_open_structures: int = 2

    @classmethod
    def from_strategy_settings(
        cls, settings: LegacyIronCondorSettings | None = None
    ) -> "HistoricalBacktestConfig":
        active = settings or LegacyIronCondorSettings()
        return cls(
            underlying_symbol=active.underlying,
            target_dte=active.target_dte,
            min_dte=active.min_dte,
            max_dte=active.max_dte,
            wing_width=active.wing_width,
            min_credit=active.min_credit,
            take_profit_pct=active.take_profit_pct,
            stop_loss_pct=active.stop_loss_pct,
            exit_dte=active.exit_dte,
            min_vix=active.min_vix,
            max_vix=active.max_vix,
            max_open_structures=active.max_open_structures,
        )


@dataclass(slots=True)
class HistoricalTradeResult:
    entry_date: date
    exit_date: date
    expiry: date
    entry_price: float
    exit_price: float
    proxy_vix: float
    implied_volatility: float
    short_put_strike: float
    long_put_strike: float
    short_call_strike: float
    long_call_strike: float
    credit_received: float
    pnl: float
    exit_reason: str
    dte_at_entry: int
    dte_at_exit: int

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entry_date"] = self.entry_date.isoformat()
        payload["exit_date"] = self.exit_date.isoformat()
        payload["expiry"] = self.expiry.isoformat()
        return payload


class AlpacaHistoricalBarsClient:
    def __init__(self, api_key: str, api_secret: str, data_base_url: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self.data_base_url = data_base_url.rstrip("/")

    def _request(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        full_url = f"{url}?{urlencode(params, doseq=True)}"
        request = Request(
            full_url,
            headers={
                "APCA-API-KEY-ID": self.api_key,
                "APCA-API-SECRET-KEY": self.api_secret,
            },
            method="GET",
        )
        with urlopen(request) as response:
            payload = json.loads(response.read().decode())
        return payload if isinstance(payload, dict) else {}

    def fetch_daily_bars(
        self,
        symbol: str,
        start_date: date,
        end_date: date,
    ) -> list[HistoricalBar]:
        url = f"{self.data_base_url}/v2/stocks/{symbol}/bars"
        page_token: str | None = None
        bars: list[HistoricalBar] = []

        while True:
            params: dict[str, Any] = {
                "timeframe": "1Day",
                "start": f"{start_date.isoformat()}T00:00:00Z",
                "end": f"{end_date.isoformat()}T23:59:59Z",
                "adjustment": "all",
                "sort": "asc",
                "limit": 10000,
                "feed": "iex",
            }
            if page_token:
                params["page_token"] = page_token
            payload = self._request(url, params)
            raw_bars = payload.get("bars")
            if isinstance(raw_bars, list):
                for raw_bar in raw_bars:
                    if not isinstance(raw_bar, dict):
                        continue
                    raw_timestamp = raw_bar.get("t")
                    if not isinstance(raw_timestamp, str):
                        continue
                    bars.append(
                        HistoricalBar(
                            timestamp=datetime.fromisoformat(
                                raw_timestamp.replace("Z", "+00:00")
                            ).replace(tzinfo=None),
                            open=float(raw_bar.get("o") or 0.0),
                            high=float(raw_bar.get("h") or 0.0),
                            low=float(raw_bar.get("l") or 0.0),
                            close=float(raw_bar.get("c") or 0.0),
                            volume=float(raw_bar.get("v") or 0.0),
                        )
                    )

            next_page_token = payload.get("next_page_token")
            if not isinstance(next_page_token, str) or not next_page_token:
                break
            page_token = next_page_token

        return bars


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + erf(value / sqrt(2.0)))


def _black_scholes_price(
    spot: float,
    strike: float,
    years_to_expiry: float,
    risk_free_rate: float,
    sigma: float,
    option_type: str,
) -> float:
    if years_to_expiry <= 0:
        if option_type == "put":
            return max(0.0, strike - spot)
        return max(0.0, spot - strike)
    if sigma <= 0:
        sigma = 0.0001

    d1 = (
        log(spot / strike) + (risk_free_rate + 0.5 * sigma * sigma) * years_to_expiry
    ) / (sigma * sqrt(years_to_expiry))
    d2 = d1 - sigma * sqrt(years_to_expiry)
    if option_type == "call":
        return spot * _norm_cdf(d1) - strike * exp(
            -risk_free_rate * years_to_expiry
        ) * _norm_cdf(d2)
    return strike * exp(-risk_free_rate * years_to_expiry) * _norm_cdf(
        -d2
    ) - spot * _norm_cdf(-d1)


def _estimate_iv(bars: list[HistoricalBar], lookback_days: int) -> float:
    closes = [bar.close for bar in bars if bar.close > 0]
    if len(closes) < 2:
        return 0.18
    window = closes[-lookback_days:] if len(closes) >= lookback_days else closes
    if len(window) < 2:
        return 0.18
    log_returns = [log(window[idx] / window[idx - 1]) for idx in range(1, len(window))]
    if not log_returns:
        return 0.18
    mean_return = sum(log_returns) / len(log_returns)
    variance = sum((value - mean_return) ** 2 for value in log_returns) / len(
        log_returns
    )
    annualized_volatility = sqrt(variance) * sqrt(252.0)
    return max(0.10, min(0.40, annualized_volatility))


def _model_condor_credit(
    spot: float,
    expiry: date,
    as_of: date,
    iv: float,
    config: HistoricalBacktestConfig,
) -> tuple[float, dict[str, float]]:
    dte = max(0, (expiry - as_of).days)
    years_to_expiry = max(dte / 365.0, 1 / 365.0)
    strikes = calculate_condor_strikes(price=spot, wing_width=config.wing_width)
    short_put = _black_scholes_price(
        spot, strikes["short_put"], years_to_expiry, config.risk_free_rate, iv, "put"
    )
    long_put = _black_scholes_price(
        spot, strikes["long_put"], years_to_expiry, config.risk_free_rate, iv, "put"
    )
    short_call = _black_scholes_price(
        spot, strikes["short_call"], years_to_expiry, config.risk_free_rate, iv, "call"
    )
    long_call = _black_scholes_price(
        spot, strikes["long_call"], years_to_expiry, config.risk_free_rate, iv, "call"
    )
    raw_credit = (short_put - long_put) + (short_call - long_call)
    credit = max(0.0, raw_credit * (1.0 - config.slippage_pct))
    return round(credit, 4), strikes


def _entry_timestamp(entry_date: date) -> datetime:
    return datetime.combine(entry_date, time(hour=9, minute=30))


def _simulate_trade(
    entry_index: int,
    tradeable_bars: list[HistoricalBar],
    all_bars: list[HistoricalBar],
    config: HistoricalBacktestConfig,
) -> tuple[HistoricalTradeResult | None, str | None]:
    entry_bar = tradeable_bars[entry_index]
    entry_date = entry_bar.timestamp.date()
    history = [bar for bar in all_bars if bar.timestamp.date() <= entry_date]
    iv = _estimate_iv(history, config.iv_lookback_days)
    proxy_vix = round(iv * 100.0, 2)
    if proxy_vix < config.min_vix:
        return None, f"proxy_vix_below_min:{proxy_vix:.2f}"
    if proxy_vix > config.max_vix:
        return None, f"proxy_vix_above_max:{proxy_vix:.2f}"

    expiry = calculate_target_expiry(
        now=_entry_timestamp(entry_date),
        target_dte=config.target_dte,
        min_dte=config.min_dte,
        max_dte=config.max_dte,
    )
    credit, strikes = _model_condor_credit(
        spot=entry_bar.open,
        expiry=expiry,
        as_of=entry_date,
        iv=iv,
        config=config,
    )
    if credit < config.min_credit:
        return None, f"credit_below_min:{credit:.2f}"

    exit_cutoff = expiry - timedelta(days=config.exit_dte)
    future_bars = [
        bar for bar in tradeable_bars if entry_date < bar.timestamp.date() <= expiry
    ]
    candidate_exit_bars = [
        bar for bar in future_bars if bar.timestamp.date() >= exit_cutoff
    ]
    if not candidate_exit_bars:
        return None, "insufficient_future_bars"

    final_bar = candidate_exit_bars[-1]
    exit_reason = "exit_dte"
    exit_credit = credit
    exit_date = final_bar.timestamp.date()
    exit_price = final_bar.close

    for current_bar in future_bars:
        current_date = current_bar.timestamp.date()
        dte_remaining = max(0, (expiry - current_date).days)
        history_to_date = [
            bar for bar in all_bars if bar.timestamp.date() <= current_date
        ]
        current_iv = _estimate_iv(history_to_date, config.iv_lookback_days)
        current_mark, _ = _model_condor_credit(
            spot=current_bar.close,
            expiry=expiry,
            as_of=current_date,
            iv=current_iv,
            config=config,
        )
        pnl = round((credit - current_mark) * 100.0, 2)
        if pnl >= round(credit * config.take_profit_pct * 100.0, 2):
            exit_reason = "profit_target"
            exit_credit = current_mark
            exit_date = current_date
            exit_price = current_bar.close
            break
        if pnl <= round(-credit * config.stop_loss_pct * 100.0, 2):
            exit_reason = "stop_loss"
            exit_credit = current_mark
            exit_date = current_date
            exit_price = current_bar.close
            break
        if dte_remaining <= config.exit_dte:
            exit_reason = "exit_dte"
            exit_credit = current_mark
            exit_date = current_date
            exit_price = current_bar.close
            break

    dte_at_entry = (expiry - entry_date).days
    dte_at_exit = max(0, (expiry - exit_date).days)
    return (
        HistoricalTradeResult(
            entry_date=entry_date,
            exit_date=exit_date,
            expiry=expiry,
            entry_price=round(entry_bar.open, 2),
            exit_price=round(exit_price, 2),
            proxy_vix=proxy_vix,
            implied_volatility=round(iv, 4),
            short_put_strike=strikes["short_put"],
            long_put_strike=strikes["long_put"],
            short_call_strike=strikes["short_call"],
            long_call_strike=strikes["long_call"],
            credit_received=round(credit * 100.0, 2),
            pnl=round((credit - exit_credit) * 100.0, 2),
            exit_reason=exit_reason,
            dte_at_entry=dte_at_entry,
            dte_at_exit=dte_at_exit,
        ),
        None,
    )


def _entry_capacity_blocker(
    entry_date: date,
    expiry: date,
    results: list[HistoricalTradeResult],
    config: HistoricalBacktestConfig,
) -> str | None:
    active_trades = [
        result
        for result in results
        if result.entry_date <= entry_date <= result.exit_date
    ]
    if len(active_trades) >= config.max_open_structures:
        return "max_open_structures_reached"
    if any(result.expiry == expiry for result in active_trades):
        return f"expiry_already_open:{expiry.isoformat()}"
    return None


def _build_summary(
    results: list[HistoricalTradeResult],
    skip_reasons: dict[str, int],
    start_date: date,
    end_date: date,
    config: HistoricalBacktestConfig,
) -> dict[str, Any]:
    scenario_count = len(results)
    total_pnl = round(sum(result.pnl for result in results), 2)
    wins = [result for result in results if result.pnl > 0]
    losses = [result for result in results if result.pnl < 0]
    flats = [result for result in results if result.pnl == 0]
    exit_reason_counts: dict[str, int] = {}
    for result in results:
        exit_reason_counts[result.exit_reason] = (
            exit_reason_counts.get(result.exit_reason, 0) + 1
        )

    avg_pnl = round(total_pnl / scenario_count, 2) if scenario_count else 0.0
    win_rate_pct = (
        round((len(wins) / scenario_count) * 100.0, 2) if scenario_count else 0.0
    )
    return {
        "scenario_count": scenario_count,
        "total_pnl": total_pnl,
        "avg_pnl": avg_pnl,
        "win_rate_pct": win_rate_pct,
        "wins": len(wins),
        "losses": len(losses),
        "flat": len(flats),
        "max_win": round(max((result.pnl for result in results), default=0.0), 2),
        "max_loss": round(min((result.pnl for result in results), default=0.0), 2),
        "exit_reason_counts": exit_reason_counts,
        "skipped_entries": sum(skip_reasons.values()),
        "skip_reasons": skip_reasons,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "config": asdict(config),
    }


def run_historical_backtest(
    *,
    api_key: str,
    api_secret: str,
    data_base_url: str,
    strategy_id: str = "legacy-iron-condor",
    days: int = 90,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict[str, Any]:
    if start_date is None or end_date is None:
        resolved_end_date = date.today() - timedelta(days=1)
        resolved_start_date = resolved_end_date - timedelta(days=days)
    else:
        resolved_start_date = start_date
        resolved_end_date = end_date

    config = HistoricalBacktestConfig.from_strategy_settings()
    client = AlpacaHistoricalBarsClient(api_key, api_secret, data_base_url)
    history_start = resolved_start_date - timedelta(days=60)
    bars = client.fetch_daily_bars(
        config.underlying_symbol, history_start, resolved_end_date
    )
    tradeable_bars = [
        bar
        for bar in bars
        if resolved_start_date <= bar.timestamp.date() <= resolved_end_date
    ]

    results: list[HistoricalTradeResult] = []
    skip_reasons: dict[str, int] = {}
    index = 0
    while index < len(tradeable_bars):
        entry_date = tradeable_bars[index].timestamp.date()
        expiry = calculate_target_expiry(
            now=_entry_timestamp(entry_date),
            target_dte=config.target_dte,
            min_dte=config.min_dte,
            max_dte=config.max_dte,
        )
        capacity_blocker = _entry_capacity_blocker(entry_date, expiry, results, config)
        if capacity_blocker is not None:
            skip_reasons[capacity_blocker] = skip_reasons.get(capacity_blocker, 0) + 1
            index += config.entry_spacing_trading_days
            continue

        result, skip_reason = _simulate_trade(index, tradeable_bars, bars, config)
        if result is not None:
            results.append(result)
        elif skip_reason is not None:
            skip_reasons[skip_reason] = skip_reasons.get(skip_reason, 0) + 1
        index += config.entry_spacing_trading_days

    aggregate = _build_summary(
        results=results,
        skip_reasons=skip_reasons,
        start_date=resolved_start_date,
        end_date=resolved_end_date,
        config=config,
    )
    return {
        "generated_at": utc_now().isoformat(),
        "strategy_id": strategy_id,
        "scenario_set": "historical-bars",
        "replay_mode": "modeled-options-on-real-bars",
        "limitations": [
            "uses historical SPY daily bars from Alpaca",
            "models option prices with Black-Scholes instead of historical option-chain quotes",
            "uses realized-volatility proxy for the VIX gate",
            "not a quote-by-quote options replay",
        ],
        "scenarios": [result.to_dict() for result in results],
        "aggregate": aggregate,
    }
