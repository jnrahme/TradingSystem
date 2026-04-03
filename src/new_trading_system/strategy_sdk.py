from __future__ import annotations

from typing import Protocol

from .models import StrategyContext, StrategyManifest, StrategyOutcome


class StrategyPlugin(Protocol):
    def manifest(self) -> StrategyManifest:
        ...

    def generate(self, context: StrategyContext) -> StrategyOutcome:
        ...

