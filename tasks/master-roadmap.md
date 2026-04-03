# TradingSystem Master Roadmap

## Phase 0 — Foundation

- [ ] Create a project-wide architecture decision record for canonical state, risk path, and strategy contract.
- [ ] Add CI checks for schema validation, markdown lint, Python syntax, and basic repo hygiene.
- [ ] Define the canonical event envelope and market-state schemas.
- [ ] Define the canonical ledger schema and promotion-stage model.
- [ ] Add environment templates for local research, paper trading, and future live deployment.

## Phase 1 — Loop System Adaptation

- [x] Adapt the loop system so sequential mode supports Codex, Claude, and OpenCode backends.
- [x] Replace UE5-specific agent prompts with trading-specific audit, todo, review, and orchestrator agents.
- [x] Write a project decision context tuned for trading, research, risk, and reversibility.
- [x] Add a loop-system README with safe usage examples for backlog execution.
- [x] Validate the loop scripts with help commands and a dry-run workflow.

## Phase 2 — Market Intelligence Core

- [ ] Define the daily market note data model.
- [ ] Define the market regime label taxonomy.
- [ ] Build a macro-event ingestion plan covering Fed, inflation, labor, GDP, Treasury, and earnings.
- [ ] Define the first cross-asset watchlist and rationale.
- [ ] Create a market-state feature inventory document.
- [ ] Implement placeholder schemas for event intelligence and market intelligence outputs.

## Phase 3 — Research Lab

- [ ] Build a replay harness specification for broad ETF regime strategies.
- [ ] Define baseline strategies for momentum, mean-reversion, and event response.
- [ ] Add a result schema for backtest / replay outputs.
- [ ] Define evaluation metrics for regime quality, expectancy, drawdown, and live drift.
- [ ] Create the first research notebook or script scaffold for broad-market strategy evaluation.

## Phase 4 — Data Stack

- [ ] Choose the low-cost initial market data path for ETF and crypto research.
- [ ] Choose the initial news / event ingestion path.
- [ ] Define archival storage layout for raw events, normalized features, and replay bundles.
- [ ] Define data-quality checks for stale data, gaps, split handling, and schema drift.

## Phase 5 — Strategy Families

- [ ] Create the `broad-market-regime` strategy family folder and manifest.
- [ ] Create the `defined-risk-options` strategy family folder and manifest.
- [ ] Create the `crypto-regime` strategy family folder and manifest.
- [ ] Write acceptance rules for when a strategy may graduate from replay to paper.

## Phase 6 — Simulation and Brokers

- [ ] Define the internal paper broker contract.
- [ ] Define the broker capability registry.
- [ ] Build a first pass on Alpaca adapter requirements.
- [ ] Build a first pass on IBKR adapter requirements.
- [ ] Build a first pass on Coinbase adapter requirements.
- [ ] Write reconciliation requirements for broker fills versus canonical ledger.

## Phase 7 — Dashboard and Operators

- [ ] Define the dashboard read models for strategy leaderboard, portfolio health, and incidents.
- [ ] Define promotion and kill-switch workflows for the operator console.
- [ ] Define daily review and post-trade attribution reports.

## Phase 8 — Live Readiness

- [ ] Define canary capital rules.
- [ ] Define hard kill conditions for data, broker, and strategy drift.
- [ ] Define a pre-live checklist for the first deployed strategy.
- [ ] Define rollback and incident runbooks.
