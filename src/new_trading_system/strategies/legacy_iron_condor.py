from __future__ import annotations

from dataclasses import dataclass
from ..models import (
    AssetClass,
    IntentPurpose,
    OptionLeg,
    OrderIntent,
    OrderType,
    Side,
    StrategyAlert,
    StrategyContext,
    StrategyManifest,
    StrategyOutcome,
)
from ..occ import calculate_condor_strikes, calculate_target_expiry, group_condors
from ..time_utils import utc_now


@dataclass(slots=True)
class LegacyIronCondorSettings:
    underlying: str = "SPY"
    target_dte: int = 30
    min_dte: int = 21
    max_dte: int = 45
    wing_width: float = 10.0
    min_credit: float = 0.50
    take_profit_pct: float = 0.50
    stop_loss_pct: float = 1.00
    exit_dte: int = 7
    max_open_structures: int = 1
    quantity: int = 1


class LegacyIronCondorStrategy:
    def __init__(self, settings: LegacyIronCondorSettings | None = None):
        self.settings = settings or LegacyIronCondorSettings()

    def manifest(self) -> StrategyManifest:
        return StrategyManifest(
            strategy_id="legacy-iron-condor",
            family="options-trading",
            version="1.0.0",
            asset_classes=(AssetClass.OPTION_MULTI_LEG, AssetClass.OPTION),
            description="Extracted legacy SPY iron condor entry and exit behavior.",
            enabled_by_default=True,
            paper_only_by_default=True,
            requires_manual_live_approval=True,
            tags=(
                "legacy",
                "options",
                "iron-condor",
                "paper-only",
                "liquid-etf-only",
                "defined-risk-only",
            ),
        )

    def _choose_contract(self, contracts, option_type: str, target_strike: float):
        matching = [contract for contract in contracts if contract.option_type == option_type]
        if not matching:
            raise ValueError(f"no {option_type} contracts for expiry")
        return min(matching, key=lambda contract: abs(contract.strike - target_strike))

    def _build_entry(self, context: StrategyContext) -> OrderIntent | None:
        if len(group_condors(context.positions, as_of=context.now.date())) >= self.settings.max_open_structures:
            return None

        underlying_quote = context.market.get_stock_quote(self.settings.underlying)
        price = underlying_quote.midpoint or underlying_quote.last or 0.0
        if price <= 0:
            return None

        expiry = calculate_target_expiry(
            now=context.now,
            target_dte=self.settings.target_dte,
            min_dte=self.settings.min_dte,
            max_dte=self.settings.max_dte,
        )
        dte = (expiry - context.now.date()).days
        strikes = calculate_condor_strikes(price=price, wing_width=self.settings.wing_width)
        contracts = context.market.get_option_contracts(self.settings.underlying, expiry.isoformat())
        if not contracts:
            return None

        long_put = self._choose_contract(contracts, "put", strikes["long_put"])
        short_put = self._choose_contract(contracts, "put", strikes["short_put"])
        short_call = self._choose_contract(contracts, "call", strikes["short_call"])
        long_call = self._choose_contract(contracts, "call", strikes["long_call"])
        leg_symbols = [long_put.symbol, short_put.symbol, short_call.symbol, long_call.symbol]
        quotes = context.market.get_option_quotes(leg_symbols)

        credit = round(
            quotes[short_put.symbol].midpoint
            + quotes[short_call.symbol].midpoint
            - quotes[long_put.symbol].midpoint
            - quotes[long_call.symbol].midpoint,
            2,
        )
        if credit < self.settings.min_credit:
            return None

        max_loss = round((self.settings.wing_width * 100 - credit * 100) * self.settings.quantity, 2)
        target_limit = round(max(self.settings.min_credit, credit * 0.95), 2)

        return OrderIntent(
            strategy_id=self.manifest().strategy_id,
            purpose=IntentPurpose.ENTRY,
            asset_class=AssetClass.OPTION_MULTI_LEG,
            broker=context.broker,
            symbol=self.settings.underlying,
            side=Side.SELL,
            quantity=self.settings.quantity,
            order_type=OrderType.LIMIT,
            limit_price=target_limit,
            max_loss=max_loss,
            expected_credit=credit,
            legs=[
                OptionLeg(symbol=long_put.symbol, side=Side.BUY),
                OptionLeg(symbol=short_put.symbol, side=Side.SELL),
                OptionLeg(symbol=short_call.symbol, side=Side.SELL),
                OptionLeg(symbol=long_call.symbol, side=Side.BUY),
            ],
            metadata={
                "underlying_price": price,
                "expiry": expiry.isoformat(),
                "dte": dte,
                "min_dte": self.settings.min_dte,
                "max_dte": self.settings.max_dte,
                "strategy_type": "iron_condor",
                "defined_risk": True,
                "allowed_underlyings": ["SPY", "SPX", "XSP", "QQQ", "IWM"],
                "min_credit": self.settings.min_credit,
                "strikes": strikes,
                "estimated_credit": credit,
                "exit_dte": self.settings.exit_dte,
                "take_profit_pct": self.settings.take_profit_pct,
                "stop_loss_pct": self.settings.stop_loss_pct,
                "evaluated_at": context.now.isoformat(),
            },
        )

    def _build_exit(self, context: StrategyContext, condor) -> OrderIntent | None:
        reason = None
        if condor.dte <= self.settings.exit_dte:
            reason = "exit_dte"
        elif condor.entry_credit > 0 and condor.unrealized_pl >= condor.entry_credit * self.settings.take_profit_pct:
            reason = "profit_target"
        elif condor.entry_credit > 0 and condor.unrealized_pl <= -condor.entry_credit * self.settings.stop_loss_pct:
            reason = "stop_loss"

        if reason is None:
            return None

        exit_legs = []
        for leg in condor.legs:
            exit_legs.append(
                OptionLeg(symbol=leg.symbol, side=Side.BUY if leg.qty < 0 else Side.SELL)
            )

        return OrderIntent(
            strategy_id=self.manifest().strategy_id,
            purpose=IntentPurpose.EXIT,
            asset_class=AssetClass.OPTION_MULTI_LEG,
            broker=context.broker,
            symbol=condor.underlying,
            side=Side.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            max_loss=0.0,
            expected_credit=None,
            legs=exit_legs,
            metadata={
                "reason": reason,
                "expiry": condor.expiry.isoformat(),
                "entry_credit": condor.entry_credit,
                "mark_to_close": condor.mark_to_close,
                "unrealized_pl": condor.unrealized_pl,
                "dte": condor.dte,
                "strategy_type": "iron_condor",
                "defined_risk": True,
                "allowed_underlyings": ["SPY", "SPX", "XSP", "QQQ", "IWM"],
            },
        )

    def generate(self, context: StrategyContext) -> StrategyOutcome:
        condors = group_condors(
            [
                position
                for position in context.positions
                if position.symbol.startswith(self.settings.underlying)
            ],
            as_of=context.now.date(),
        )

        alerts = [
            StrategyAlert(
                level="info",
                message="legacy strategy is paper-only and routed through the platform engine",
            )
        ]
        intents = []

        for condor in condors:
            exit_intent = self._build_exit(context, condor)
            if exit_intent:
                intents.append(exit_intent)

        if not intents and context.clock.is_open:
            entry_intent = self._build_entry(context)
            if entry_intent:
                intents.append(entry_intent)
        elif not context.clock.is_open:
            alerts.append(StrategyAlert(level="info", message="market closed, entry generation skipped"))

        return StrategyOutcome(
            intents=intents,
            alerts=alerts,
            state_snapshot={
                "last_run_at": utc_now().isoformat(),
                "open_condors": len(condors),
                "generated_intents": len(intents),
            },
        )
