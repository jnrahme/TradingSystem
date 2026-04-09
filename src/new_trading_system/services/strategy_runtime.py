from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from ..models import (
    AccountSnapshot,
    MarketClock,
    Position,
    StrategyContext,
    StrategyOutcome,
)
from .portfolio_ledger import PortfolioLedger


@dataclass(slots=True)
class JsonStrategyStateStore:
    root: Path

    def load(self, strategy_id: str) -> dict[str, Any]:
        path = self.root / f"{strategy_id}.json"
        if not path.exists():
            return {}
        return json.loads(path.read_text())

    def save(self, strategy_id: str, snapshot: dict[str, Any]) -> None:
        path = self.root / f"{strategy_id}.json"
        path.write_text(json.dumps(snapshot, indent=2, sort_keys=True))


class StrategyStateStore(Protocol):
    def load(self, strategy_id: str) -> dict[str, Any]: ...

    def save(self, strategy_id: str, snapshot: dict[str, Any]) -> None: ...


class StrategyRuntime:
    def __init__(self, ledger: PortfolioLedger, state_store: StrategyStateStore):
        self.ledger = ledger
        self.state_store = state_store

    def evaluate(
        self,
        strategies: list[Any],
        account: AccountSnapshot,
        clock: MarketClock,
        positions: list[Position],
        market,
        broker_name: str,
    ) -> dict[str, StrategyOutcome]:
        outcomes: dict[str, StrategyOutcome] = {}
        for strategy in strategies:
            manifest = strategy.manifest()
            state_snapshot = self.state_store.load(manifest.strategy_id)
            context = StrategyContext(
                manifest=manifest,
                account=account,
                clock=clock,
                positions=positions,
                state_snapshot=state_snapshot,
                market=market,
                broker=broker_name,
                now=clock.timestamp,
            )
            outcome = strategy.generate(context)
            outcomes[manifest.strategy_id] = outcome
            self.state_store.save(manifest.strategy_id, outcome.state_snapshot)
            self.ledger.record_strategy_run(
                strategy_id=manifest.strategy_id,
                broker=broker_name,
                market_open=clock.is_open,
                alerts_count=len(outcome.alerts),
                intents_count=len(outcome.intents),
                state_snapshot=outcome.state_snapshot,
            )
        return outcomes
