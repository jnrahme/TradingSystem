from __future__ import annotations

from typing import Any

from ..models import StrategyManifest


def _as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _strategy_score(scorecard: dict[str, Any], strategy_id: str) -> dict[str, Any]:
    strategies = scorecard.get("strategies")
    if isinstance(strategies, list):
        for strategy in strategies:
            if (
                isinstance(strategy, dict)
                and strategy.get("strategy_id") == strategy_id
            ):
                return strategy
    return {"strategy_id": strategy_id}


def evaluate_strategy_promotion(
    manifest: StrategyManifest,
    scorecard: dict[str, Any],
) -> dict[str, Any]:
    minimum_replay_win_rate_pct = getattr(manifest, "minimum_replay_win_rate_pct", None)
    minimum_replay_total_pnl = getattr(manifest, "minimum_replay_total_pnl", None)
    strategy = _strategy_score(scorecard, manifest.strategy_id)
    replay_reports = strategy.get("replay_reports")
    if not isinstance(replay_reports, list):
        replay_reports = []

    qualifying_replay_reports = [
        report
        for report in replay_reports
        if isinstance(report, dict)
        and report.get("replay_mode") != "synthetic-internal-paper"
    ]
    total_replay_scenarios = sum(
        _as_int(report.get("scenario_count")) for report in qualifying_replay_reports
    )
    historical_reports = [
        report
        for report in qualifying_replay_reports
        if isinstance(report, dict)
        and report.get("replay_mode") == "modeled-options-on-real-bars"
    ]
    historical_replay_win_rate_pct = _as_float_or_none(
        historical_reports[-1].get("win_rate_pct") if historical_reports else None
    )
    historical_replay_total_pnl = _as_float_or_none(
        historical_reports[-1].get("total_pnl") if historical_reports else None
    )
    paper_entry_fills = _as_int(
        strategy.get("effective_paper_entry_fills", strategy.get("paper_entry_fills"))
    )
    paper_exit_fills = _as_int(
        strategy.get("effective_paper_exit_fills", strategy.get("paper_exit_fills"))
    )
    observed_days = _as_int(
        strategy.get("effective_observed_days", strategy.get("observed_days"))
    )
    estimated_win_rate_pct = _as_float_or_none(
        strategy.get(
            "effective_estimated_win_rate_pct", strategy.get("estimated_win_rate_pct")
        )
    )
    estimated_realized_pl = _as_float_or_none(
        strategy.get(
            "effective_estimated_realized_pl_from_filled_exits",
            strategy.get("estimated_realized_pl_from_filled_exits"),
        )
    )

    checks = [
        {
            "name": "replay_scenarios",
            "required": manifest.minimum_replay_scenarios,
            "actual": total_replay_scenarios,
            "passed": total_replay_scenarios >= manifest.minimum_replay_scenarios,
            "reason": (
                f"needs at least {manifest.minimum_replay_scenarios} replay scenarios"
                if total_replay_scenarios < manifest.minimum_replay_scenarios
                else ""
            ),
        },
        {
            "name": "paper_entry_fills",
            "required": manifest.minimum_paper_entry_fills,
            "actual": paper_entry_fills,
            "passed": paper_entry_fills >= manifest.minimum_paper_entry_fills,
            "reason": (
                f"needs at least {manifest.minimum_paper_entry_fills} filled paper entries"
                if paper_entry_fills < manifest.minimum_paper_entry_fills
                else ""
            ),
        },
        {
            "name": "paper_exit_fills",
            "required": manifest.minimum_paper_exit_fills,
            "actual": paper_exit_fills,
            "passed": paper_exit_fills >= manifest.minimum_paper_exit_fills,
            "reason": (
                f"needs at least {manifest.minimum_paper_exit_fills} filled paper exits"
                if paper_exit_fills < manifest.minimum_paper_exit_fills
                else ""
            ),
        },
        {
            "name": "observed_days",
            "required": manifest.minimum_observed_days,
            "actual": observed_days,
            "passed": observed_days >= manifest.minimum_observed_days,
            "reason": (
                f"needs at least {manifest.minimum_observed_days} observed paper days"
                if observed_days < manifest.minimum_observed_days
                else ""
            ),
        },
    ]

    if manifest.minimum_estimated_win_rate_pct is not None:
        checks.append(
            {
                "name": "estimated_win_rate_pct",
                "required": manifest.minimum_estimated_win_rate_pct,
                "actual": estimated_win_rate_pct,
                "passed": estimated_win_rate_pct is not None
                and estimated_win_rate_pct >= manifest.minimum_estimated_win_rate_pct,
                "reason": (
                    f"needs estimated win rate >= {manifest.minimum_estimated_win_rate_pct:.2f}%"
                    if estimated_win_rate_pct is None
                    or estimated_win_rate_pct < manifest.minimum_estimated_win_rate_pct
                    else ""
                ),
            }
        )

    if minimum_replay_win_rate_pct is not None:
        checks.append(
            {
                "name": "historical_replay_win_rate_pct",
                "required": minimum_replay_win_rate_pct,
                "actual": historical_replay_win_rate_pct,
                "passed": historical_replay_win_rate_pct is not None
                and historical_replay_win_rate_pct >= minimum_replay_win_rate_pct,
                "reason": (
                    f"needs historical replay win rate >= {minimum_replay_win_rate_pct:.2f}%"
                    if historical_replay_win_rate_pct is None
                    or historical_replay_win_rate_pct < minimum_replay_win_rate_pct
                    else ""
                ),
            }
        )

    if minimum_replay_total_pnl is not None:
        checks.append(
            {
                "name": "historical_replay_total_pnl",
                "required": minimum_replay_total_pnl,
                "actual": historical_replay_total_pnl,
                "passed": historical_replay_total_pnl is not None
                and historical_replay_total_pnl >= minimum_replay_total_pnl,
                "reason": (
                    f"needs historical replay total P/L >= {minimum_replay_total_pnl:.2f}"
                    if historical_replay_total_pnl is None
                    or historical_replay_total_pnl < minimum_replay_total_pnl
                    else ""
                ),
            }
        )

    if manifest.minimum_estimated_realized_pl is not None:
        checks.append(
            {
                "name": "estimated_realized_pl_from_filled_exits",
                "required": manifest.minimum_estimated_realized_pl,
                "actual": estimated_realized_pl,
                "passed": estimated_realized_pl is not None
                and estimated_realized_pl >= manifest.minimum_estimated_realized_pl,
                "reason": (
                    f"needs estimated realized P/L >= {manifest.minimum_estimated_realized_pl:.2f}"
                    if estimated_realized_pl is None
                    or estimated_realized_pl < manifest.minimum_estimated_realized_pl
                    else ""
                ),
            }
        )

    blockers = [
        check["reason"] for check in checks if not check["passed"] and check["reason"]
    ]
    automatic_gate_passed = not blockers

    verdict = (
        "ready_for_manual_live_review"
        if automatic_gate_passed and manifest.requires_manual_live_approval
        else "eligible_for_live_consideration"
        if automatic_gate_passed
        else "blocked"
    )

    return {
        "strategy_id": manifest.strategy_id,
        "account_id": scorecard.get("account_id"),
        "broker": scorecard.get("broker"),
        "requires_manual_live_approval": manifest.requires_manual_live_approval,
        "paper_only_by_default": manifest.paper_only_by_default,
        "verdict": verdict,
        "automatic_gate_passed": automatic_gate_passed,
        "checks": checks,
        "blockers": blockers,
        "evidence": {
            "replay_reports": replay_reports,
            "historical_replay_win_rate_pct": historical_replay_win_rate_pct,
            "historical_replay_total_pnl": historical_replay_total_pnl,
            "paper_entry_fills": paper_entry_fills,
            "paper_exit_fills": paper_exit_fills,
            "observed_days": observed_days,
            "estimated_win_rate_pct": estimated_win_rate_pct,
            "estimated_realized_pl_from_filled_exits": estimated_realized_pl,
        },
    }
