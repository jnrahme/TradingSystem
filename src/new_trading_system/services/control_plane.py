from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StrategyRegistry:
    _strategies: dict[str, Any] = field(default_factory=dict)

    def register(self, strategy: Any) -> None:
        self._strategies[strategy.manifest().strategy_id] = strategy

    def resolve(self, requested: list[str] | None = None) -> list[Any]:
        if requested is None:
            return [
                strategy
                for strategy in self._strategies.values()
                if strategy.manifest().enabled_by_default
            ]
        return [
            self._strategies[strategy_id]
            for strategy_id in requested
            if strategy_id in self._strategies
        ]

    def list_ids(self) -> list[str]:
        return sorted(self._strategies)
