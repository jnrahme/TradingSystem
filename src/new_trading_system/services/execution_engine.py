from __future__ import annotations

from ..broker_sdk import BrokerAdapter
from ..models import OrderIntent, OrderResult, OrderStatus, StrategyManifest
from ..time_utils import utc_now
from .portfolio_ledger import PortfolioLedger
from .risk_engine import RiskEngine


class ExecutionEngine:
    def __init__(
        self, broker: BrokerAdapter, ledger: PortfolioLedger, risk_engine: RiskEngine
    ):
        self.broker = broker
        self.ledger = ledger
        self.risk_engine = risk_engine

    def process(
        self,
        manifest: StrategyManifest,
        account,
        positions,
        intents: list[OrderIntent],
        market_open: bool,
        dry_run: bool = True,
    ) -> list[OrderResult]:
        results: list[OrderResult] = []
        for intent in intents:
            self.ledger.record_intent(intent)
            intraday_metrics = self.ledger.get_intraday_metrics(
                self.broker.name, account
            )
            try:
                intraday_metrics = self.ledger.merge_broker_intraday_metrics(
                    self.broker.name,
                    account,
                    self.broker.list_orders(status="all", limit=200),
                )
            except Exception:
                pass
            decision = self.risk_engine.evaluate(
                manifest=manifest,
                account=account,
                positions=positions,
                intent=intent,
                market_open=market_open,
                broker_mode=self.broker.mode,
                intraday_metrics=intraday_metrics,
            )

            if not decision.approved:
                result = OrderResult(
                    order_id=f"rejected-{intent.intent_id}",
                    intent_id=intent.intent_id,
                    strategy_id=intent.strategy_id,
                    broker=self.broker.name,
                    status=OrderStatus.REJECTED,
                    submitted_at=utc_now(),
                    raw={
                        "reasons": decision.reasons,
                        "warnings": decision.warnings,
                        "checks": decision.checks,
                    },
                )
                self.ledger.record_order_result(intent, result)
                results.append(result)
                continue

            if dry_run:
                result = OrderResult(
                    order_id=f"dryrun-{intent.intent_id}",
                    intent_id=intent.intent_id,
                    strategy_id=intent.strategy_id,
                    broker=self.broker.name,
                    status=OrderStatus.SKIPPED,
                    submitted_at=utc_now(),
                    raw={
                        "warnings": decision.warnings,
                        "checks": decision.checks,
                        "dry_run": True,
                    },
                    fill_price=intent.limit_price,
                )
                self.ledger.record_order_result(intent, result)
                results.append(result)
                continue

            result = self.broker.submit_order(intent)
            result.raw.setdefault("warnings", decision.warnings)
            result.raw.setdefault("checks", decision.checks)
            self.ledger.record_order_result(intent, result)
            results.append(result)
            positions = self.broker.get_positions()
            account = self.broker.get_account_snapshot()

        refreshed_positions = self.broker.get_positions()
        self.ledger.replace_positions(self.broker.name, refreshed_positions)
        return results
