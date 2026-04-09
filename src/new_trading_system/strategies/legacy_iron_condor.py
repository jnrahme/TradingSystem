from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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
    find_condor_structure_issues,
    group_condors,
)
from ..time_utils import utc_now


@dataclass(slots=True)
class LegacyIronCondorSettings:
    underlying: str = "SPY"
    vix_symbol: str = "VIX"
    min_vix: float = 12.0
    max_vix: float = 35.0
    target_dte: int = 30
    min_dte: int = 11
    max_dte: int = 52
    wing_width: float = 10.0
    min_credit: float = 0.40
    take_profit_pct: float = 0.025
    stop_loss_pct: float = 1.00
    exit_dte: int = 10
    max_open_structures: int = 8
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
            minimum_replay_scenarios=30,
            minimum_paper_entry_fills=1,
            minimum_paper_exit_fills=3,
            minimum_observed_days=3,
            minimum_replay_win_rate_pct=50.0,
            minimum_replay_total_pnl=0.0,
            minimum_estimated_win_rate_pct=50.0,
            minimum_estimated_realized_pl=0.0,
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
        matching = [
            contract for contract in contracts if contract.option_type == option_type
        ]
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
        if expiry_iso and any(
            condor.expiry.isoformat() == expiry_iso for condor in condors
        ):
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
        vix_level: float | None = None,
    ) -> tuple[OrderIntent | None, str | None]:
        entry_blocker = self._entry_blocker_message(condors, structure_issues)
        if entry_blocker:
            return None, entry_blocker

        underlying_quote = context.market.get_stock_quote(self.settings.underlying)
        price = underlying_quote.midpoint or underlying_quote.last or 0.0
        if price <= 0:
            return None, "entry skipped because the underlying price is unavailable"

        strikes = calculate_condor_strikes(
            price=price, wing_width=self.settings.wing_width
        )
        expiry, dte, contracts, expiry_blocker = self._select_entry_expiry(
            context, condors
        )
        if expiry_blocker:
            return None, expiry_blocker
        if expiry is None or dte is None or contracts is None:
            return None, "entry skipped because no eligible expiry could be selected"

        long_put = self._choose_contract(contracts, "put", strikes["long_put"])
        short_put = self._choose_contract(contracts, "put", strikes["short_put"])
        short_call = self._choose_contract(contracts, "call", strikes["short_call"])
        long_call = self._choose_contract(contracts, "call", strikes["long_call"])
        leg_symbols = [
            long_put.symbol,
            short_put.symbol,
            short_call.symbol,
            long_call.symbol,
        ]
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

        max_loss = round(
            (self.settings.wing_width * 100 - credit * 100) * self.settings.quantity, 2
        )
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
                    "vix_symbol": self.settings.vix_symbol,
                    "vix_level": vix_level,
                    "min_vix": self.settings.min_vix,
                    "max_vix": self.settings.max_vix,
                    "exit_dte": self.settings.exit_dte,
                    "take_profit_pct": self.settings.take_profit_pct,
                    "stop_loss_pct": self.settings.stop_loss_pct,
                    "evaluated_at": context.now.isoformat(),
                },
            ),
            None,
        )

    def _candidate_expiries(self, as_of: date) -> list[tuple[date, int]]:
        candidates: list[tuple[date, int]] = []
        for days_out in range(self.settings.min_dte, self.settings.max_dte + 1):
            if days_out <= self.settings.exit_dte:
                continue
            candidate = as_of + timedelta(days=days_out)
            if candidate.weekday() != 4:
                continue
            candidates.append((candidate, days_out))

        candidates.sort(
            key=lambda item: (abs(item[1] - self.settings.target_dte), item[1])
        )
        return candidates

    def _select_entry_expiry(
        self,
        context: StrategyContext,
        condors: list[CondorSnapshot],
    ) -> tuple[date | None, int | None, list | None, str | None]:
        open_expiries = {condor.expiry.isoformat() for condor in condors}
        blocked_expiry: str | None = None

        for expiry, dte in self._candidate_expiries(context.now.date()):
            expiry_iso = expiry.isoformat()
            if expiry_iso in open_expiries:
                if blocked_expiry is None:
                    blocked_expiry = expiry_iso
                continue

            contracts = context.market.get_option_contracts(
                self.settings.underlying,
                expiry_iso,
            )
            if contracts:
                return expiry, dte, contracts, None

        if blocked_expiry is not None:
            return (
                None,
                None,
                None,
                f"entry skipped because expiry {blocked_expiry} is already open",
            )

        return (
            None,
            None,
            None,
            "entry skipped because no contracts were returned for any expiry in the configured DTE window",
        )

    def _evaluate_vix_gate(
        self,
        context: StrategyContext,
    ) -> tuple[str | None, float | None, str | None]:
        try:
            quote = context.market.get_stock_quote(self.settings.vix_symbol)
        except Exception as exc:
            return (
                None,
                None,
                f"vix gate unavailable for {self.settings.vix_symbol}: {exc}",
            )

        vix_level = quote.midpoint or quote.last or 0.0
        if vix_level <= 0:
            return (
                None,
                None,
                f"vix gate unavailable for {self.settings.vix_symbol}: invalid quote",
            )
        if vix_level < self.settings.min_vix:
            return (
                f"entry skipped because VIX {vix_level:.2f} is below minimum {self.settings.min_vix:.2f}",
                vix_level,
                None,
            )
        if vix_level > self.settings.max_vix:
            return (
                f"entry skipped because VIX {vix_level:.2f} is above maximum {self.settings.max_vix:.2f}",
                vix_level,
                None,
            )
        return None, vix_level, None

    def _exit_reason_details(self, condor: CondorSnapshot, reason: str) -> str:
        if condor.entry_credit <= 0:
            return f"{reason} triggered with no recorded entry credit"

        pnl_pct = (condor.unrealized_pl / condor.entry_credit) * 100
        if reason == "exit_dte":
            return f"{condor.dte} DTE remaining"
        if reason == "profit_target":
            target_pct = self.settings.take_profit_pct * 100
            return f"{pnl_pct:.1f}% profit versus {target_pct:g}% target"
        if reason == "stop_loss":
            stop_pct = self.settings.stop_loss_pct * 100
            return f"{pnl_pct:.1f}% loss versus {stop_pct:g}% stop"
        return f"reason={reason}"

    def _build_exit(
        self, broker_name: str, condor: CondorSnapshot
    ) -> OrderIntent | None:
        reason = None
        if condor.dte <= self.settings.exit_dte:
            reason = "exit_dte"
        elif (
            condor.entry_credit > 0
            and condor.unrealized_pl
            >= condor.entry_credit * self.settings.take_profit_pct
        ):
            reason = "profit_target"
        elif (
            condor.entry_credit > 0
            and condor.unrealized_pl
            <= -condor.entry_credit * self.settings.stop_loss_pct
        ):
            reason = "stop_loss"

        if reason is None:
            return None

        exit_legs = [
            OptionLeg(symbol=leg.symbol, side=Side.BUY if leg.qty < 0 else Side.SELL)
            for leg in condor.legs
        ]
        contracts = max(1.0, max(abs(leg.qty) for leg in condor.legs))
        per_spread_mark = condor.mark_to_close / (100.0 * contracts)
        target_limit = round(max(0.01, per_spread_mark * 1.03), 2)

        return OrderIntent(
            strategy_id=self.manifest().strategy_id,
            purpose=IntentPurpose.EXIT,
            asset_class=AssetClass.OPTION_MULTI_LEG,
            broker=broker_name,
            symbol=condor.underlying,
            side=Side.BUY,
            quantity=1,
            order_type=OrderType.LIMIT,
            limit_price=target_limit,
            max_loss=0.0,
            expected_credit=None,
            legs=exit_legs,
            metadata={
                "reason": reason,
                "reason_detail": self._exit_reason_details(condor, reason),
                "expiry": condor.expiry.isoformat(),
                "entry_credit": condor.entry_credit,
                "mark_to_close": condor.mark_to_close,
                "target_limit": target_limit,
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
        vix_level: float | None = None
        vix_gate_note: str | None = None

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
            blocked_entry_reason = self._entry_blocker_message(
                condors, structure_issues
            )

        if not intents and context.clock.is_open and blocked_entry_reason is None:
            blocked_entry_reason, vix_level, vix_gate_note = self._evaluate_vix_gate(
                context
            )
            if vix_gate_note:
                alerts.append(StrategyAlert(level="info", message=vix_gate_note))

        if not intents and context.clock.is_open and blocked_entry_reason is None:
            entry_intent, blocked_entry_reason = self._build_entry(
                context,
                condors=condors,
                structure_issues=structure_issues,
                vix_level=vix_level,
            )
            if entry_intent:
                intents.append(entry_intent)
            elif blocked_entry_reason:
                alerts.append(StrategyAlert(level="info", message=blocked_entry_reason))
        elif not intents and context.clock.is_open and blocked_entry_reason:
            alerts.append(StrategyAlert(level="info", message=blocked_entry_reason))
        elif not context.clock.is_open:
            alerts.append(
                StrategyAlert(
                    level="info", message="market closed, entry generation skipped"
                )
            )

        return StrategyOutcome(
            intents=intents,
            alerts=alerts,
            state_snapshot={
                "last_run_at": utc_now().isoformat(),
                "open_condors": len(condors),
                "open_expiries": sorted(
                    condor.expiry.isoformat() for condor in condors
                ),
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
                "vix_level": vix_level,
                "vix_gate_note": vix_gate_note,
                "blocked_entry_reason": blocked_entry_reason,
                "generated_intents": len(intents),
            },
        )
