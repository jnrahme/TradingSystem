from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import os
from pathlib import Path
import time

from ..adapters.alpaca_paper import AlpacaPaperBrokerAdapter
from ..adapters.internal_paper import InternalPaperBrokerAdapter, build_demo_snapshot
from ..config import RuntimeConfig
from ..models import OrderResult
from ..strategies.legacy_iron_condor import LegacyIronCondorStrategy
from .control_plane import StrategyRegistry
from .execution_engine import ExecutionEngine
from .portfolio_ledger import LedgerSummary, PortfolioLedger
from .risk_engine import RiskEngine
from .strategy_runtime import JsonStrategyStateStore, StrategyRuntime


@dataclass(slots=True)
class WorkerReport:
    broker: str
    dry_run: bool
    results: list[OrderResult]
    summary: LedgerSummary


class WorkerLockBusyError(RuntimeError):
    pass


@contextmanager
def worker_execution_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+", encoding="utf-8")
    locked = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError as exc:
            raise WorkerLockBusyError(
                f"worker execution already in progress for lock {lock_path}"
            ) from exc

        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()))
        handle.flush()
        yield
    finally:
        if locked:
            try:
                handle.seek(0)
                handle.truncate()
                handle.flush()
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def build_broker(config: RuntimeConfig, broker_name: str):
    if broker_name == "internal-paper":
        return InternalPaperBrokerAdapter.from_state_file(
            snapshot=build_demo_snapshot(),
            state_path=config.internal_paper_state_path,
        )
    if broker_name == "alpaca-paper":
        if not config.alpaca_api_key or not config.alpaca_api_secret:
            raise ValueError("alpaca paper credentials are missing from .env.paper.local")
        return AlpacaPaperBrokerAdapter(
            api_key=config.alpaca_api_key,
            api_secret=config.alpaca_api_secret,
            trading_base_url=config.alpaca_trading_base_url,
            data_base_url=config.alpaca_data_base_url,
        )
    raise ValueError(f"unsupported broker: {broker_name}")


def build_registry() -> StrategyRegistry:
    registry = StrategyRegistry()
    registry.register(LegacyIronCondorStrategy())
    return registry


class PaperTradingWorker:
    def __init__(self, config: RuntimeConfig, broker_name: str):
        self.config = config
        self.broker_name = broker_name
        self.broker = build_broker(config, broker_name)
        self.ledger = PortfolioLedger(config.state_db_path)
        self.runtime = StrategyRuntime(
            ledger=self.ledger,
            state_store=JsonStrategyStateStore(config.strategy_state_dir),
        )
        self.risk_engine = RiskEngine()
        self.execution = ExecutionEngine(broker=self.broker, ledger=self.ledger, risk_engine=self.risk_engine)
        self.registry = build_registry()

    def _refresh_broker(self) -> None:
        self.broker = build_broker(self.config, self.broker_name)
        self.execution = ExecutionEngine(
            broker=self.broker,
            ledger=self.ledger,
            risk_engine=self.risk_engine,
        )

    def run_once(self, strategy_ids: list[str] | None = None, dry_run: bool = True) -> WorkerReport:
        with worker_execution_lock(self.config.worker_lock_path):
            self._refresh_broker()
            clock = self.broker.get_clock()
            account = self.broker.get_account_snapshot()
            positions = self.broker.get_positions()
            self.ledger.replace_positions(self.broker.name, positions)

            strategies = self.registry.resolve(strategy_ids)
            outcomes = self.runtime.evaluate(
                strategies=strategies,
                account=account,
                clock=clock,
                positions=positions,
                market=self.broker,
                broker_name=self.broker.name,
            )

            results: list[OrderResult] = []
            for strategy in strategies:
                manifest = strategy.manifest()
                outcome = outcomes[manifest.strategy_id]
                results.extend(
                    self.execution.process(
                        manifest=manifest,
                        account=account,
                        positions=self.broker.get_positions(),
                        intents=outcome.intents,
                        market_open=clock.is_open,
                        dry_run=dry_run,
                    )
                )

            final_account = self.broker.get_account_snapshot()
            summary = self.ledger.write_summary(
                self.config.dashboard_summary_path,
                final_account,
                broker=self.broker.name,
            )
            if isinstance(self.broker, InternalPaperBrokerAdapter):
                self.broker.save_state(self.config.internal_paper_state_path)
            return WorkerReport(
                broker=self.broker.name,
                dry_run=dry_run,
                results=results,
                summary=summary,
            )

    def run_loop(
        self,
        strategy_ids: list[str] | None = None,
        dry_run: bool = True,
        interval_seconds: int = 300,
        max_iterations: int | None = None,
    ) -> list[WorkerReport]:
        reports: list[WorkerReport] = []
        iteration = 0
        while max_iterations is None or iteration < max_iterations:
            reports.append(self.run_once(strategy_ids=strategy_ids, dry_run=dry_run))
            iteration += 1
            if max_iterations is not None and iteration >= max_iterations:
                break
            time.sleep(interval_seconds)
        return reports
