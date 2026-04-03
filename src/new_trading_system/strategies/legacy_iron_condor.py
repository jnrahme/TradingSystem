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
from ..occ import (
    CondorSnapshot,
    CondorStructureIssue,
    calculate_condor_strikes,
    calculate_target_expiry,
    find_condor_structure_issues,
    group_condors,
)
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
    max_open_structures: int = 2
    quantity: int = 1


class LegacyIronCondorStrategy:
    def __init__(self, settings: LegacyIronCondorSettings | None = None):
        self.settings = settings or LegacyIronCondorSettings()

    def manifest(self) -> StrategyManifest:
        return StrategyManifest(
            strategy_id="legacy-iron-condor",
            family="options-trading",
            version="1.1.0",
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

    def _structure_positions(self, context: StrategyContext) -> list:
        return [
            position
            for position in context.positions
            if position.symbol.startswith(self.settings.underlying)
        ]

    def _entry_blocker_message(
        self,
        condors: list[CondorSnapshot],
        structure_issues: list[CondorStructureIssue],
        expiry_iso: str | None = None,
        credit: float | None = None,
    ) -> str | None:
        if structure_issues:
            return "entry skipped because a non-canonical iron condor structure needs operator review"
        if len(condors) >= self.settings.max_open_structures:
            return (
                "entry skipped because max open condors is already reached "
                f"({len(condors)}/{self.settings.max_open_structures})"
            )
        if expiry_iso and any(condor.expiry.isoformat() == expiry_iso for condor in condors):
            return f"entry skipped because expiry {expiry_iso} is already open"
        if credit is not None and credit < self.settings.min_credit:
            return (
                f"entry skipped because estimated credit {credit:.2f} is below "
                f"the minimum {self.settings.min_credit:.2f}"
            )
        return None

    def _build_entry(
        self,
        context: StrategyContext,
        condors: list[CondorSnapshot],
        structure_issues: list[CondorStructureIssue],
    ) -> tuple[OrderIntent | None, str | None]:
        entry_blocker = self._entry_blocker_message(condors, structure_issues)
        if entry_blocker:
            return None, entry_blocker

        underlying_quote = context.market.get_stock_quote(self.settings.underlying)
        price = underlying_quote.midpoint or underlying_quote.last or 0.0
        if price <= 0:
            return None, "entry skipped because the underlying price is unavailable"

        expiry = calculate_target_expiry(
            now=context.now,
            target_dte=self.settings.target_dte,
            min_dte=self.settings.min_dte,
            max_dte=self.settings.max_dte,
        )
        dte = (expiry - context.now.date()).days
        entry_blocker = self._entry_blocker_message(
            condors,
            structure_issues,
            expiry_iso=expiry.isoformat(),
        )
        if entry_blocker:
            return None, entry_blocker

        strikes = calculate_condor_strikes(price=price, wing_width=self.settings.wing_width)
        contracts = context.market.get_option_contracts(self.settings.underlying, expiry.isoformat())
        if not contracts:
            return None, f"entry skipped because no contracts were returned for expiry {expiry.isoformat()}"

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
        entry_blocker = self._entry_blocker_message(
            condors,
            structure_issues,
            expiry_iso=expiry.isoformat(),
            credit=credit,
        )
        if entry_blocker:
            return None, entry_blocker

        max_loss = round((self.settings.wing_width * 100 - credit * 100) * self.settings.quantity, 2)
        target_limit = round(max(self.settings.min_credit, credit * 0.95), 2)

        return (
            OrderIntent(
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
            ),
            None,
        )

    def _exit_reason_details(self, condor: CondorSnapshot, reason: str) -> str:
        if condor.entry_credit <= 0:
            return f"{reason} triggered with no recorded entry credit"

        pnl_pct = (condor.unrealized_pl / condor.entry_credit) * 100
        if reason == "exit_dte":
            return f"{condor.dte} DTE remaining"
        if reason == "profit_target":
            return (
                f"{pnl_pct:.1f}% profit versus {self.settings.take_profit_pct * 100:.0f}% target"
            )
        if reason == "stop_loss":
            return f"{pnl_pct:.1f}% loss versus {self.settings.stop_loss_pct * 100:.0f}% stop"
        return f"reason={reason}"

    def _build_exit(self, broker_name: str, condor: CondorSnapshot) -> OrderIntent | None:
        reason = None
        if condor.dte <= self.settings.exit_dte:
            reason = "exit_dte"
        elif condor.entry_credit > 0 and condor.unrealized_pl >= condor.entry_credit * self.settings.take_profit_pct:
            reason = "profit_target"
        elif condor.entry_credit > 0 and condor.unrealized_pl <= -condor.entry_credit * self.settings.stop_loss_pct:
            reason = "stop_loss"

        if reason is None:
            return None

        exit_legs = [
            OptionLeg(symbol=leg.symbol, side=Side.BUY if leg.qty < 0 else Side.SELL)
            for leg in condor.legs
        ]

        return OrderIntent(
            strategy_id=self.manifest().strategy_id,
            purpose=IntentPurpose.EXIT,
            asset_class=AssetClass.OPTION_MULTI_LEG,
            broker=broker_name,
            symbol=condor.underlying,
            side=Side.BUY,
            quantity=1,
            order_type=OrderType.MARKET,
            max_loss=0.0,
            expected_credit=None,
            legs=exit_legs,
            metadata={
                "reason": reason,
                "reason_detail": self._exit_reason_details(condor, reason),
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
        structure_positions = self._structure_positions(context)
        condors = group_condors(structure_positions, as_of=context.now.date())
        structure_issues = find_condor_structure_issues(
            structure_positions,
            as_of=context.now.date(),
        )

        alerts = [
            StrategyAlert(
                level="info",
                message="legacy strategy is paper-only and routed through the platform engine",
            )
        ]
        intents = []
        exit_reasons: list[str] = []
        blocked_entry_reason: str | None = None

        for issue in structure_issues:
            alerts.append(
                StrategyAlert(
                    level="warning",
                    message="non-canonical iron condor structure detected",
                    metadata={
                        "underlying": issue.underlying,
                        "expiry": issue.expiry.isoformat(),
                        "dte": issue.dte,
                        "issue": issue.issue,
                        "symbols": [leg.symbol for leg in issue.legs],
                    },
                )
            )

        for condor in condors:
            exit_intent = self._build_exit(context.broker, condor)
            if exit_intent:
                intents.append(exit_intent)
                reason = str(exit_intent.metadata.get("reason", "unknown"))
                exit_reasons.append(reason)
                alerts.append(
                    StrategyAlert(
                        level="warning" if reason == "stop_loss" else "info",
                        message=f"iron condor exit prepared: {reason}",
                        metadata={
                            "expiry": condor.expiry.isoformat(),
                            "dte": condor.dte,
                            "entry_credit": condor.entry_credit,
                            "mark_to_close": condor.mark_to_close,
                            "unrealized_pl": condor.unrealized_pl,
                            "reason_detail": exit_intent.metadata.get("reason_detail"),
                        },
                    )
                )

        if not intents and context.clock.is_open:
            entry_intent, blocked_entry_reason = self._build_entry(
                context,
                condors=condors,
                structure_issues=structure_issues,
            )
            if entry_intent:
                intents.append(entry_intent)
            elif blocked_entry_reason:
                alerts.append(StrategyAlert(level="info", message=blocked_entry_reason))
        elif not context.clock.is_open:
            alerts.append(StrategyAlert(level="info", message="market closed, entry generation skipped"))

        return StrategyOutcome(
            intents=intents,
            alerts=alerts,
            state_snapshot={
                "last_run_at": utc_now().isoformat(),
                "open_condors": len(condors),
                "open_expiries": sorted(condor.expiry.isoformat() for condor in condors),
                "structure_issues": [
                    {
                        "underlying": issue.underlying,
                        "expiry": issue.expiry.isoformat(),
                        "dte": issue.dte,
                        "issue": issue.issue,
                        "symbols": [leg.symbol for leg in issue.legs],
                    }
                    for issue in structure_issues
                ],
                "exit_reasons": exit_reasons,
                "blocked_entry_reason": blocked_entry_reason,
                "generated_intents": len(intents),
            },
        )
