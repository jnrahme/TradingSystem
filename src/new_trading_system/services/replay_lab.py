from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from ..adapters.internal_paper import (
    InternalPaperBrokerAdapter,
    InternalPaperSnapshot,
    build_demo_snapshot,
)
from ..models import MarketClock, StrategyOutcome
from ..time_utils import utc_now
from .execution_engine import ExecutionEngine
from .portfolio_ledger import PortfolioLedger
from .risk_engine import RiskEngine
from .strategy_runtime import JsonStrategyStateStore, StrategyRuntime
from .worker import build_registry


@dataclass(slots=True)
class DemoReplayScenario:
    scenario_id: str
    description: str
    entry_time: datetime
    follow_up_time: datetime
    follow_up_mode: str


def _demo_scenarios() -> list[DemoReplayScenario]:
    return [
        DemoReplayScenario(
            scenario_id="profit-target",
            description="entry followed by a favorable repricing that should trigger the profit target exit",
            entry_time=datetime(2026, 4, 3, 14, 30),
            follow_up_time=datetime(2026, 4, 3, 14, 35),
            follow_up_mode="profit_target",
        ),
        DemoReplayScenario(
            scenario_id="stop-loss",
            description="entry followed by an adverse repricing that should trigger the stop loss exit",
            entry_time=datetime(2026, 4, 3, 14, 30),
            follow_up_time=datetime(2026, 4, 3, 14, 35),
            follow_up_mode="stop_loss",
        ),
        DemoReplayScenario(
            scenario_id="exit-dte",
            description="entry held until the configured DTE exit threshold is reached",
            entry_time=datetime(2026, 4, 3, 14, 30),
            follow_up_time=datetime(2026, 5, 1, 14, 30),
            follow_up_mode="exit_dte",
        ),
    ]


def _scenario_snapshot(
    broker: InternalPaperBrokerAdapter,
    now: datetime,
    mode: str,
) -> InternalPaperSnapshot:
    snapshot = deepcopy(broker.snapshot)
    snapshot.clock = MarketClock(timestamp=now, is_open=True)

    if mode == "exit_dte":
        return snapshot

    for position in broker.get_positions():
        quote = snapshot.option_quotes.get(position.symbol)
        if quote is None:
            continue
        if mode == "profit_target":
            if position.qty < 0:
                quote.bid = 0.95
                quote.ask = 1.05
            else:
                quote.bid = 0.0
                quote.ask = 0.1
        elif mode == "stop_loss":
            if position.qty < 0:
                quote.bid = 10.95
                quote.ask = 11.05
            else:
                quote.bid = 0.05
                quote.ask = 0.15
    return snapshot


def _run_step(
    strategy_id: str,
    strategy_runtime: StrategyRuntime,
    execution: ExecutionEngine,
    ledger: PortfolioLedger,
    broker: InternalPaperBrokerAdapter,
) -> tuple[StrategyOutcome, list[dict[str, Any]]]:
    strategy = build_registry().resolve([strategy_id])[0]
    manifest = strategy.manifest()
    clock = broker.get_clock()
    account = broker.get_account_snapshot()
    positions = broker.get_positions()
    ledger.replace_positions(broker.name, positions)

    outcome = strategy_runtime.evaluate(
        strategies=[strategy],
        account=account,
        clock=clock,
        positions=positions,
        market=broker,
        broker_name=broker.name,
    )[manifest.strategy_id]
    results = execution.process(
        manifest=manifest,
        account=account,
        positions=broker.get_positions(),
        intents=outcome.intents,
        market_open=clock.is_open,
        dry_run=False,
    )
    return outcome, [
        {
            "order_id": result.order_id,
            "status": result.status.value,
            "fill_price": result.fill_price,
        }
        for result in results
    ]


def _run_demo_scenario(
    strategy_id: str, scenario: DemoReplayScenario
) -> dict[str, Any]:
    broker = InternalPaperBrokerAdapter(
        snapshot=build_demo_snapshot(now=scenario.entry_time)
    )
    with TemporaryDirectory(prefix=f"nts-replay-{scenario.scenario_id}-") as tempdir:
        ledger = PortfolioLedger(Path(tempdir) / "replay.sqlite3")
        state_store = JsonStrategyStateStore(Path(tempdir) / "strategy-state")
        state_store.root.mkdir(parents=True, exist_ok=True)
        strategy_runtime = StrategyRuntime(ledger=ledger, state_store=state_store)
        execution = ExecutionEngine(
            broker=broker, ledger=ledger, risk_engine=RiskEngine()
        )

        first_outcome, first_results = _run_step(
            strategy_id=strategy_id,
            strategy_runtime=strategy_runtime,
            execution=execution,
            ledger=ledger,
            broker=broker,
        )
        broker.snapshot = _scenario_snapshot(
            broker=broker,
            now=scenario.follow_up_time,
            mode=scenario.follow_up_mode,
        )
        second_outcome, second_results = _run_step(
            strategy_id=strategy_id,
            strategy_runtime=strategy_runtime,
            execution=execution,
            ledger=ledger,
            broker=broker,
        )
        scorecard = ledger.build_scorecard(
            account=broker.get_account_snapshot(),
            broker=broker.name,
            account_id=scenario.scenario_id,
            replay_recorded=True,
        )
        strategy_scorecard = next(
            (
                item
                for item in scorecard["strategies"]
                if item["strategy_id"] == strategy_id
            ),
            None,
        )
        if strategy_scorecard is None:
            raise ValueError(f"strategy scorecard missing for {strategy_id}")

        return {
            "scenario_id": scenario.scenario_id,
            "description": scenario.description,
            "steps": [
                {
                    "at": scenario.entry_time.isoformat(),
                    "generated_intents": len(first_outcome.intents),
                    "results": first_results,
                    "blocked_entry_reason": first_outcome.state_snapshot.get(
                        "blocked_entry_reason"
                    ),
                },
                {
                    "at": scenario.follow_up_time.isoformat(),
                    "generated_intents": len(second_outcome.intents),
                    "results": second_results,
                    "blocked_entry_reason": second_outcome.state_snapshot.get(
                        "blocked_entry_reason"
                    ),
                },
            ],
            "strategy": strategy_scorecard,
        }


def run_demo_replay(strategy_id: str = "legacy-iron-condor") -> dict[str, Any]:
    scenario_reports = [
        _run_demo_scenario(strategy_id=strategy_id, scenario=scenario)
        for scenario in _demo_scenarios()
    ]

    aggregate = {
        "scenario_count": len(scenario_reports),
        "paper_entry_fills": 0,
        "paper_exit_fills": 0,
        "estimated_realized_pl_from_filled_exits": 0.0,
        "estimated_closed_wins": 0,
        "estimated_closed_losses": 0,
        "estimated_closed_flat": 0,
        "exit_reason_counts": {},
    }

    for scenario_report in scenario_reports:
        strategy = scenario_report["strategy"]
        aggregate["paper_entry_fills"] += int(strategy["paper_entry_fills"])
        aggregate["paper_exit_fills"] += int(strategy["paper_exit_fills"])
        aggregate["estimated_realized_pl_from_filled_exits"] += float(
            strategy["estimated_realized_pl_from_filled_exits"]
        )
        aggregate["estimated_closed_wins"] += int(strategy["estimated_closed_wins"])
        aggregate["estimated_closed_losses"] += int(strategy["estimated_closed_losses"])
        aggregate["estimated_closed_flat"] += int(strategy["estimated_closed_flat"])
        for reason, count in strategy["exit_reason_counts"].items():
            aggregate["exit_reason_counts"][reason] = aggregate[
                "exit_reason_counts"
            ].get(reason, 0) + int(count)

    aggregate["estimated_realized_pl_from_filled_exits"] = round(
        float(aggregate["estimated_realized_pl_from_filled_exits"]),
        2,
    )

    return {
        "generated_at": utc_now().isoformat(),
        "strategy_id": strategy_id,
        "scenario_set": "demo",
        "replay_mode": "synthetic-internal-paper",
        "limitations": [
            "synthetic scenarios only",
            "not historical market replay",
            "not sufficient for live promotion on its own",
        ],
        "scenarios": scenario_reports,
        "aggregate": aggregate,
    }
