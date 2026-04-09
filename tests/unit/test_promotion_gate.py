from __future__ import annotations

import importlib

models_module = importlib.import_module("new_trading_system.models")
promotion_gate_module = importlib.import_module(
    "new_trading_system.services.promotion_gate"
)

AssetClass = models_module.AssetClass
StrategyManifest = models_module.StrategyManifest
evaluate_strategy_promotion = promotion_gate_module.evaluate_strategy_promotion


def _manifest() -> StrategyManifest:
    return StrategyManifest(
        strategy_id="legacy-iron-condor",
        family="options",
        version="1.0.0",
        asset_classes=(AssetClass.OPTION_MULTI_LEG,),
        description="test",
        minimum_replay_scenarios=30,
        minimum_paper_entry_fills=1,
        minimum_paper_exit_fills=3,
        minimum_observed_days=3,
        minimum_replay_win_rate_pct=50.0,
        minimum_replay_total_pnl=0.0,
        minimum_estimated_win_rate_pct=50.0,
        minimum_estimated_realized_pl=0.0,
        requires_manual_live_approval=True,
    )


def test_promotion_gate_blocks_when_evidence_is_insufficient() -> None:
    report = evaluate_strategy_promotion(
        manifest=_manifest(),
        scorecard={
            "account_id": "alpha",
            "broker": "internal-paper",
            "strategies": [
                {
                    "strategy_id": "legacy-iron-condor",
                    "paper_entry_fills": 1,
                    "paper_exit_fills": 0,
                    "observed_days": 1,
                    "estimated_win_rate_pct": None,
                    "estimated_realized_pl_from_filled_exits": 0.0,
                    "replay_reports": [
                        {
                            "strategy_id": "legacy-iron-condor",
                            "scenario_count": "3",
                            "replay_mode": "modeled-options-on-real-bars",
                            "win_rate_pct": "100.0",
                            "total_pnl": "10.0",
                        }
                    ],
                }
            ],
        },
    )

    assert report["verdict"] == "blocked"
    assert report["automatic_gate_passed"] is False
    assert "needs at least 3 filled paper exits" in report["blockers"]
    assert "needs at least 3 observed paper days" in report["blockers"]


def test_promotion_gate_can_reach_manual_live_review() -> None:
    report = evaluate_strategy_promotion(
        manifest=_manifest(),
        scorecard={
            "account_id": "alpha",
            "broker": "internal-paper",
            "strategies": [
                {
                    "strategy_id": "legacy-iron-condor",
                    "paper_entry_fills": 4,
                    "paper_exit_fills": 3,
                    "observed_days": 5,
                    "estimated_win_rate_pct": 66.67,
                    "estimated_realized_pl_from_filled_exits": 120.0,
                    "replay_reports": [
                        {
                            "strategy_id": "legacy-iron-condor",
                            "scenario_count": "30",
                            "replay_mode": "modeled-options-on-real-bars",
                            "win_rate_pct": "66.67",
                            "total_pnl": "120.0",
                        }
                    ],
                }
            ],
        },
    )

    assert report["verdict"] == "ready_for_manual_live_review"
    assert report["automatic_gate_passed"] is True
    assert report["blockers"] == []


def test_promotion_gate_ignores_synthetic_demo_replay_for_sample_threshold() -> None:
    report = evaluate_strategy_promotion(
        manifest=_manifest(),
        scorecard={
            "account_id": "alpha",
            "broker": "internal-paper",
            "strategies": [
                {
                    "strategy_id": "legacy-iron-condor",
                    "paper_entry_fills": 4,
                    "paper_exit_fills": 3,
                    "observed_days": 5,
                    "estimated_win_rate_pct": 66.67,
                    "estimated_realized_pl_from_filled_exits": 120.0,
                    "replay_reports": [
                        {
                            "strategy_id": "legacy-iron-condor",
                            "scenario_count": "100",
                            "replay_mode": "synthetic-internal-paper",
                            "win_rate_pct": "",
                            "total_pnl": "",
                        }
                    ],
                }
            ],
        },
    )

    assert report["verdict"] == "blocked"
    assert "needs at least 30 replay scenarios" in report["blockers"]
