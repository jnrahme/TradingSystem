from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..models import (
    AccountSnapshot,
    AssetClass,
    IntentPurpose,
    OrderIntent,
    OrderType,
    Position,
    RiskDecision,
    StrategyManifest,
)
from ..occ import estimate_condor_max_loss, extract_underlying, group_condors

LIQUID_OPTIONS_UNDERLYINGS = frozenset({"SPY", "SPX", "XSP", "QQQ", "IWM"})
FORBIDDEN_STRATEGY_TYPES = frozenset(
    {"naked_put", "naked_call", "short_straddle", "short_strangle"}
)


@dataclass(slots=True)
class RiskPolicy:
    max_position_risk_pct: float = 0.05
    max_cumulative_risk_pct: float = 0.10
    max_open_condors: int = 8
    max_positions: int = 8
    max_daily_loss_pct: float = 0.02
    max_daily_structures: int = 8
    max_daily_fills: int = 20
    allowed_underlyings: frozenset[str] = field(
        default_factory=lambda: LIQUID_OPTIONS_UNDERLYINGS
    )
    forbidden_strategy_types: frozenset[str] = field(
        default_factory=lambda: FORBIDDEN_STRATEGY_TYPES
    )


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None):
        self.policy = policy or RiskPolicy()

    def _position_slot_limit(self, intent: OrderIntent) -> int:
        if intent.asset_class is AssetClass.OPTION_MULTI_LEG:
            leg_count = max(1, len(intent.legs))
            return max(
                self.policy.max_positions, self.policy.max_open_condors * leg_count
            )
        return self.policy.max_positions

    def _is_opening_intent(self, intent: OrderIntent) -> bool:
        return intent.purpose is IntentPurpose.ENTRY

    def _symbols_for_intent(self, intent: OrderIntent) -> list[str]:
        return [leg.symbol for leg in intent.legs] or [intent.symbol]

    def _underlyings_for_intent(self, intent: OrderIntent) -> list[str]:
        return sorted(
            {extract_underlying(symbol) for symbol in self._symbols_for_intent(intent)}
        )

    def _intent_strategy_type(self, intent: OrderIntent) -> str | None:
        strategy_type = intent.metadata.get("strategy_type")
        if strategy_type is None:
            return None
        return str(strategy_type).strip().lower() or None

    def _allowed_underlyings(
        self, manifest: StrategyManifest, intent: OrderIntent
    ) -> frozenset[str] | None:
        explicit = intent.metadata.get("allowed_underlyings")
        if isinstance(explicit, (list, tuple, set, frozenset)):
            normalized = {
                str(value).strip().upper() for value in explicit if str(value).strip()
            }
            return frozenset(normalized) if normalized else None
        if "liquid-etf-only" in manifest.tags:
            return self.policy.allowed_underlyings
        return None

    def _intraday_metrics(
        self, account: AccountSnapshot, intraday_metrics: dict[str, Any] | None
    ) -> dict[str, float | int]:
        source: dict[str, Any] = {}
        if isinstance(account.metadata, dict):
            source.update(account.metadata)
        if intraday_metrics:
            source.update(intraday_metrics)

        def _as_float(value: Any) -> float:
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0

        def _as_int(value: Any) -> int:
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0

        return {
            "daily_pnl": _as_float(source.get("daily_pnl", 0.0)),
            "fills_today": _as_int(source.get("fills_today", 0)),
            "structures_today": _as_int(source.get("structures_today", 0)),
            "orders_today": _as_int(source.get("orders_today", 0)),
        }

    def _estimate_existing_open_risk(self, positions: list[Position]) -> float:
        condors = group_condors(positions)
        condor_symbols = {leg.symbol for condor in condors for leg in condor.legs}
        existing_risk = sum(estimate_condor_max_loss(condor) for condor in condors)

        for position in positions:
            if position.symbol in condor_symbols:
                continue
            raw_max_loss = (
                position.metadata.get("max_loss")
                if isinstance(position.metadata, dict)
                else None
            )
            try:
                existing_risk += max(float(raw_max_loss or 0.0), 0.0)
            except (TypeError, ValueError):
                continue
        return round(existing_risk, 2)

    def _estimate_required_capital(self, intent: OrderIntent) -> float | None:
        if intent.max_loss is not None:
            return max(float(intent.max_loss), 0.0)
        if intent.limit_price is None:
            return None
        multiplier = (
            100.0
            if intent.asset_class in (AssetClass.OPTION, AssetClass.OPTION_MULTI_LEG)
            else 1.0
        )
        return round(intent.limit_price * intent.quantity * multiplier, 2)

    def evaluate(
        self,
        manifest: StrategyManifest,
        account: AccountSnapshot,
        positions: list[Position],
        intent: OrderIntent,
        market_open: bool,
        broker_mode: str,
        intraday_metrics: dict[str, Any] | None = None,
    ) -> RiskDecision:
        reasons: list[str] = []
        warnings: list[str] = []
        checks: list[str] = []
        is_opening = self._is_opening_intent(intent)
        intent_symbols = self._symbols_for_intent(intent)

        if manifest.paper_only_by_default and not broker_mode.startswith("paper"):
            reasons.append("paper-only strategy cannot route to non-paper broker")
        checks.append(f"broker_mode:{broker_mode}")

        if is_opening and not market_open:
            reasons.append("market is closed for new entries")
        elif not market_open:
            warnings.append(
                "market is closed; closing and repair intents stay permitted"
            )
        checks.append(f"market_open:{market_open}")

        if account.status.upper() != "ACTIVE":
            reasons.append(f"account status is {account.status}")
        checks.append(f"account_status:{account.status.upper()}")

        if is_opening and account.equity <= 0:
            reasons.append("cannot trade with zero equity")
        checks.append(f"equity:{account.equity:.2f}")

        if intent.order_type is OrderType.LIMIT and intent.limit_price is None:
            reasons.append("limit orders require limit_price")

        if intent.asset_class is AssetClass.OPTION_MULTI_LEG and len(intent.legs) < 2:
            reasons.append("multi-leg intents require at least two legs")

        allowed_underlyings = self._allowed_underlyings(manifest, intent)
        if allowed_underlyings:
            blocked_underlyings = [
                underlying
                for underlying in self._underlyings_for_intent(intent)
                if underlying not in allowed_underlyings
            ]
            if blocked_underlyings:
                reasons.append(
                    "underlying not allowed for this strategy: "
                    + ", ".join(sorted(blocked_underlyings))
                )
            else:
                checks.append("underlying_whitelist:PASS")
        else:
            checks.append("underlying_whitelist:SKIP")

        strategy_type = self._intent_strategy_type(intent)
        if (
            is_opening
            and strategy_type
            and strategy_type in self.policy.forbidden_strategy_types
        ):
            reasons.append(f"forbidden strategy type: {strategy_type}")

        if (
            is_opening
            and intent.asset_class is AssetClass.OPTION_MULTI_LEG
            and intent.metadata.get("defined_risk") is False
        ):
            reasons.append("multi-leg options entries must be defined-risk")

        if is_opening:
            dte = intent.metadata.get("dte")
            min_dte = intent.metadata.get("min_dte")
            max_dte = intent.metadata.get("max_dte")
            try:
                dte_value = int(dte) if dte is not None else None
            except (TypeError, ValueError):
                dte_value = None
            try:
                min_dte_value = int(min_dte) if min_dte is not None else None
            except (TypeError, ValueError):
                min_dte_value = None
            try:
                max_dte_value = int(max_dte) if max_dte is not None else None
            except (TypeError, ValueError):
                max_dte_value = None

            if (
                dte_value is not None
                and min_dte_value is not None
                and dte_value < min_dte_value
            ):
                reasons.append(f"dte {dte_value} is below minimum {min_dte_value}")
            if (
                dte_value is not None
                and max_dte_value is not None
                and dte_value > max_dte_value
            ):
                reasons.append(f"dte {dte_value} is above maximum {max_dte_value}")

        if intent.max_loss and account.equity > 0:
            risk_pct = intent.max_loss / account.equity
            if risk_pct > self.policy.max_position_risk_pct:
                reasons.append(
                    f"intent max loss {intent.max_loss:.2f} exceeds "
                    f"{self.policy.max_position_risk_pct:.0%} of equity"
                )
        if intent.max_loss:
            checks.append(f"intent_max_loss:{float(intent.max_loss):.2f}")

        max_position_slots = self._position_slot_limit(intent)
        if is_opening and len(positions) >= max_position_slots:
            reasons.append(
                f"position count {len(positions)} reached max {max_position_slots}"
            )

        existing_symbols = {position.symbol for position in positions}
        if is_opening:
            overlapping_symbols = [
                symbol for symbol in intent_symbols if symbol in existing_symbols
            ]
            if overlapping_symbols:
                reasons.append(
                    "position stacking blocked; already holding "
                    + ", ".join(sorted(overlapping_symbols))
                )

        if is_opening and intent.asset_class is AssetClass.OPTION_MULTI_LEG:
            open_condors = len(group_condors(positions))
            if open_condors >= self.policy.max_open_condors:
                reasons.append(
                    f"max open condors reached ({open_condors}/{self.policy.max_open_condors})"
                )
            checks.append(f"open_condors:{open_condors}")

        if is_opening and account.equity > 0:
            existing_open_risk = self._estimate_existing_open_risk(positions)
            projected_risk = existing_open_risk + max(
                float(intent.max_loss or 0.0), 0.0
            )
            cumulative_risk_limit = account.equity * self.policy.max_cumulative_risk_pct
            if intent.max_loss and projected_risk > cumulative_risk_limit:
                reasons.append(
                    f"projected open risk {projected_risk:.2f} exceeds "
                    f"{self.policy.max_cumulative_risk_pct:.0%} of equity"
                )
            checks.append(f"existing_open_risk:{existing_open_risk:.2f}")

        required_capital = self._estimate_required_capital(intent)
        if (
            is_opening
            and required_capital is not None
            and required_capital > account.buying_power
        ):
            reasons.append(
                f"required capital {required_capital:.2f} exceeds buying power {account.buying_power:.2f}"
            )

        metrics = self._intraday_metrics(account, intraday_metrics)
        checks.append(
            "intraday_metrics:"
            f" pnl={metrics['daily_pnl']:+.2f}"
            f" fills={metrics['fills_today']}"
            f" structures={metrics['structures_today']}"
        )
        if is_opening and account.equity > 0:
            if metrics["daily_pnl"] < -(
                account.equity * self.policy.max_daily_loss_pct
            ):
                reasons.append(
                    f"daily loss limit exceeded: {metrics['daily_pnl']:+.2f} < "
                    f"-{self.policy.max_daily_loss_pct:.0%} of equity"
                )
            if (
                intent.asset_class is AssetClass.OPTION_MULTI_LEG
                and metrics["structures_today"] >= self.policy.max_daily_structures
            ):
                reasons.append(
                    f"max structures guardrail hit: "
                    f"{metrics['structures_today']}/{self.policy.max_daily_structures} today"
                )
            if metrics["fills_today"] >= self.policy.max_daily_fills:
                reasons.append(
                    f"max fills guardrail hit: {metrics['fills_today']}/{self.policy.max_daily_fills} today"
                )

        min_credit = float(intent.metadata.get("min_credit", 0.5) or 0.5)
        if intent.expected_credit and intent.expected_credit < min_credit:
            warnings.append(
                f"expected credit {intent.expected_credit:.2f} is below the minimum threshold {min_credit:.2f}"
            )

        return RiskDecision(
            approved=not reasons, reasons=reasons, warnings=warnings, checks=checks
        )
