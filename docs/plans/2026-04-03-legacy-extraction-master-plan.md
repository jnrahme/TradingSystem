# Legacy Extraction Master Plan

Last updated: 2026-04-03

## Mission

Extract everything useful from the legacy `trading` repo and re-home it inside `NewTradingSystem` without importing the architectural drift, operational clutter, or stale data baggage that accumulated in the old system.

The goal is not repository parity by size.

The goal is platform parity by useful capability.

See `docs/legacy-inventory.md` for the concrete bucket-by-bucket extraction list.

## What We Measured

Measured on 2026-04-03:

- Legacy repo size: about `1.2G`
- New repo checkout remains in the single-digit megabytes before counting extra local worktrees
- Legacy `src` size: about `3.4M`
- Legacy `scripts` size: about `2.0M`
- Legacy `data` size: about `257M`
- Legacy workflow count: `90`
- Legacy strategy file count: `12`
- Legacy Python source files in `src`: `197`
- Legacy Python scripts: `135`
- Legacy Python tests: `211`

This confirms the big gap is partly capability, but heavily driven by git history, worktrees, docs, logs, and accumulated data artifacts.

## Extraction Rule

Every legacy asset must be classified into one of four buckets:

1. `Extract`
   Preserve behavior with minimal translation because the behavior is useful and already matches the new boundaries closely enough.
2. `Redesign`
   Keep the idea, but rebuild it cleanly for the new platform.
3. `Reference-Only`
   Keep as research input or historical context, not runtime code.
4. `Discard`
   Do not port because it is one-off, stale, redundant, or harmful to the new architecture.

## Platform Boundaries We Must Protect

These boundaries are non-negotiable in the new repo:

- strategies do not call brokers directly
- strategies do not own persistence or dashboard writes
- broker adapters do not own PnL truth
- workflows do not encode business logic that belongs in the platform
- paper-only remains the default
- runtime state stays out of git

## Legacy Inventory By Domain

### 1. Strategies

Legacy files:

- `src/strategies/iron_condor/*`
- `scripts/iron_condor_trader.py`
- `scripts/manage_iron_condor_positions.py`
- `src/strategies/momentum_strategy.py`
- `src/strategies/legacy_momentum.py`
- `src/strategies/reit_strategy.py`
- `src/strategies/rule_one_options.py`
- `src/strategies/vix_mean_reversion.py`
- `src/strategies/core_strategy.py`

Treatment:

- `legacy iron condor`: `extract + redesign`
- `vix mean reversion`: `extract`
- `momentum`: `reference-only until replay lab is ready`
- `rule one options`: `reference-only first, then redesign`
- `reit`: `reference-only`
- `core_strategy.py`: `discard as runtime shape, keep as reference`

### 2. Risk And Safety

Legacy sources:

- `src/risk/trade_gateway.py`
- `src/safety/mandatory_trade_gate.py`
- `src/safety/*`
- `scripts/pre_trade_checklist.py`
- `scripts/verify_*`
- `scripts/cancel_stale_orders.py`

Treatment:

- the ideas are strong
- the implementation is too coupled to legacy scripts and file state
- this domain is `redesign`, not direct copy

Priority rules to port first:

- paper-only enforcement
- market-hours gating for entries
- position risk caps
- open-structure caps
- ticker / universe restrictions where relevant
- closing orders must remain possible even when opening orders are blocked

### 3. Execution And Broker Integration

Legacy sources:

- `src/execution/*`
- `src/brokers/*`
- options order construction in the iron condor files
- reconciliation and sync scripts like `sync_alpaca_state.py`, `sync_trades_from_alpaca.py`, `verify_trade_execution.py`

Treatment:

- broker payload knowledge: `extract`
- runtime shape: `redesign`
- one-off sync scripts: mostly `reference-only` until folded into services

Priority:

1. Alpaca paper order lifecycle
2. position and order reconciliation
3. stale order cleanup
4. execution-quality logging
5. future broker registry for IBKR and Coinbase

### 4. Research, Replay, Learning, And Analytics

Legacy sources:

- `src/backtest/*`
- `src/research/*`
- `src/analytics/*`
- `src/learning/*`
- `src/rag/*`
- `src/ml/*`
- `data/backtests/*`
- scripts like `run_core_strategy_reference_backtest.py`, `build_sqlite_analytics.py`

Treatment:

- the concepts are valuable
- the old implementations are too mixed with operational history
- this domain is mostly `redesign`

Extract first:

- result schema ideas
- replay evaluation ideas
- historical strategy comparison ideas
- lessons-learned ingestion patterns

### 5. CLIs And Operational Scripts

Legacy repo has more than one hundred scripts. They should not be ported one by one.

Instead, they should be collapsed into a smaller set of product-grade entrypoints.

Target new CLI groups:

- `worker`
- `reconcile`
- `verify`
- `replay`
- `research`
- `ops`

Useful script families to absorb:

- health checks
- verification commands
- reconciliation/sync commands
- emergency close logic
- analytics builders

Script families to leave behind:

- content publishing
- SEO/blog automation
- one-off repo maintenance helpers
- workflow glue that exists only because the old repo had too many scripts

### 6. Workflows And GitHub Actions

Legacy workflow count is `90`.

That is a warning sign, not a target.

We should replace them with a smaller workflow surface:

- CI
- docs validation
- replay jobs
- scheduled paper worker wrapper if needed
- dashboard publish
- health monitor
- emergency operator workflow

Workflow migration rule:

- if a workflow is product runtime, move the logic into code first
- if a workflow is verification or publishing, keep it as CI/CD
- if a workflow is one-off glue, discard it

## Extraction Matrix

| Legacy Area | Example Sources | New Home | Treatment | Priority |
| --- | --- | --- | --- | --- |
| Iron condor entry/exit | `scripts/iron_condor_trader.py`, `scripts/manage_iron_condor_positions.py` | `src/new_trading_system/strategies/legacy_iron_condor.py` | extract + redesign | highest |
| VIX signal | `src/signals/vix_mean_reversion_signal.py`, `src/strategies/vix_mean_reversion.py` | `src/new_trading_system/strategies/` and future market intelligence layer | extract | high |
| Gateway risk rules | `src/risk/trade_gateway.py` | `src/new_trading_system/services/risk_engine.py` | redesign | highest |
| Mandatory order safety | `src/safety/mandatory_trade_gate.py` | execution + risk services | redesign | highest |
| Alpaca execution knowledge | `src/execution/*`, options MLEG code | `src/new_trading_system/adapters/alpaca_paper.py` | extract + redesign | high |
| Broker reconciliation | `sync_*`, `verify_*`, state sync scripts | new reconcile service/CLI | redesign | high |
| Replay and backtests | `src/backtest/*`, `data/backtests/*` | future research lab | redesign | high |
| Analytics summaries | sqlite analytics scripts and reports | future research lab + dashboard read models | redesign | medium |
| Momentum and other strategies | strategy modules in legacy repo | future strategy families | reference-only first | medium |
| Blog/content/SEO automations | content and publishing scripts/workflows | not part of runtime platform | discard or separate repo concern | low |

## Program Phases

### Phase A — Inventory Freeze

- write the extraction map
- document current truth
- define discard/reference/extract/redesign decisions

### Phase B — Core Engine Parity

- strengthen risk engine with legacy gateway rules
- add reconciliation and stale-order handling
- add market-hours scheduling and operator kill switches

### Phase C — Options Parity

- finish iron condor lifecycle parity
- port VIX and options-selection helpers
- support order and position management parity on Alpaca paper

### Phase D — CLI Consolidation

- absorb useful verification and sync scripts into the new CLI
- remove dependence on one-off script sprawl

### Phase E — Research And Replay

- design the replay lab
- carry over useful evaluation ideas
- define promotion scorecards

### Phase F — Strategy Expansion

- extract the next useful strategy families
- keep them behind the same engine boundaries

### Phase G — Workflow Replacement

- replace high-value workflows with a smaller, cleaner set
- do not recreate the legacy workflow count

### Phase H — Documentation And Operator Clarity

- keep current-state docs synchronized
- maintain the HTML portal
- publish only docs that reflect the truth of the app

## What “Good Legacy Parity” Means

We should consider the old repo successfully absorbed when:

- every important trading behavior lives behind the new runtime boundaries
- the key legacy options behavior works from the new worker
- useful legacy strategies are plugins, not scripts
- useful safety logic is centralized in the new risk and execution services
- legacy sync and verify behaviors exist as clean new CLI commands
- the operator can understand the system from the docs without reading random scripts

## Immediate Next Extraction Targets

Completed on 2026-04-03:

1. Ported the strongest risk rules from `trade_gateway.py` into `risk_engine.py`
2. Ported the mandatory opening-vs-closing order safety concepts from `mandatory_trade_gate.py`
3. Collapsed useful legacy verification and sync scripts into first-pass `reconcile` and `verify` CLI commands
4. Added broker-versus-ledger reconciliation plus stale-order verification and cancellation hooks
5. Made worktree checkouts reuse the root `.env.paper.local` so paper-broker verification still works on isolated branches
6. Added first-pass iron-condor lifecycle parity: profit-target, stop-loss, and DTE exits, duplicate-expiry blocking, and broken-structure alerts

Next:

7. Finish iron-condor scanner and signal parity beyond the current lifecycle controls
8. Define the broker capability registry
9. Port VIX mean reversion logic into the new strategy and market layer
10. Start replay-lab scaffolding for strategy promotion
11. Define the reduced workflow set that replaces the useful legacy GitHub Actions
