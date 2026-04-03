from __future__ import annotations

from dataclasses import dataclass

from ..models import AccountSnapshot, IntentPurpose, OrderIntent, Position, RiskDecision, StrategyManifest
from ..occ import group_condors


@dataclass(slots=True)
class RiskPolicy:
    max_position_risk_pct: float = 0.05
    max_open_condors: int = 2


class RiskEngine:
    def __init__(self, policy: RiskPolicy | None = None):
        self.policy = policy or RiskPolicy()

    def evaluate(
        self,
        manifest: StrategyManifest,
        account: AccountSnapshot,
        positions: list[Position],
        intent: OrderIntent,
        market_open: bool,
        broker_mode: str,
    ) -> RiskDecision:
        reasons: list[str] = []
        warnings: list[str] = []

        if manifest.paper_only_by_default and not broker_mode.startswith("paper"):
            reasons.append("paper-only strategy cannot route to non-paper broker")

        if intent.purpose is IntentPurpose.ENTRY and not market_open:
            reasons.append("market is closed for new entries")

        if account.status.upper() != "ACTIVE":
            reasons.append(f"account status is {account.status}")

        if intent.max_loss and account.equity > 0:
            risk_pct = intent.max_loss / account.equity
            if risk_pct > self.policy.max_position_risk_pct:
                reasons.append(
                    f"intent max loss {intent.max_loss:.2f} exceeds "
                    f"{self.policy.max_position_risk_pct:.0%} of equity"
                )

        if intent.purpose is IntentPurpose.ENTRY and intent.asset_class.value == "option_multi_leg":
            open_condors = len(group_condors(positions))
            if open_condors >= self.policy.max_open_condors:
                reasons.append(
                    f"max open condors reached ({open_condors}/{self.policy.max_open_condors})"
                )

        if intent.expected_credit and intent.expected_credit < 0.5:
            warnings.append("expected credit is below the default minimum threshold")

        return RiskDecision(approved=not reasons, reasons=reasons, warnings=warnings)

