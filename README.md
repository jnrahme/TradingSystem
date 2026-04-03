# NewTradingSystem

This repository is scaffolded as a broker-agnostic, multi-strategy trading platform.

Start with:

- `index.html` for the platform redesign brief
- `docs/legacy-extraction-portal.html` for the published legacy-extraction and moving-parts overview
- `docs/legacy-inventory.md` for the concrete list of high-value legacy strategies, scripts, workflows, and migration buckets
- `docs/current-state.md` for the plain-English truth of what is actually built today
- `docs/plans/2026-04-03-legacy-extraction-master-plan.md` for the migration program from the old trading repo
- `docs/plans/2026-04-03-market-intelligence-master-plan.md` for the market-intelligence and growth strategy
- `tasks/master-roadmap.md` for the execution backlog
- `loop-system/README.md` for the autonomous build/research loop
- `.env.paper.local.example` for the local paper-broker credential shape

The repo is organized so the trading system, strategies, reusable SDKs, dashboards, schemas, and infrastructure can evolve independently.

Core operating assumption:

- Paper-only is the default operating mode.
- Strategies never place broker orders directly.
- The platform owns execution, risk, reconciliation, persistence, and promotion gates.
- Every strategy must pass replay, internal paper trading, and broker-paper validation before any live capital is considered.
- No strategy moves to real money without explicit live-approval criteria and manual promotion.
- Real broker credentials live only in a local `.env.paper.local` file, which is git-ignored and should stay machine-local.

First runnable vertical slice:

- `src/new_trading_system/services/worker.py`: paper worker orchestration
- `src/new_trading_system/services/execution_engine.py`: intent-to-broker execution path with ledger-backed intraday checks
- `src/new_trading_system/services/risk_engine.py`: paper-only, opening-vs-closing, whitelist, and cumulative-risk guardrails extracted from the legacy gateway
- `src/new_trading_system/services/reconciliation.py`: position reconciliation, verification, and stale-order handling
- `src/new_trading_system/services/portfolio_ledger.py`: canonical SQLite-backed ledger and dashboard summary
- `src/new_trading_system/adapters/internal_paper.py`: internal simulator broker
- `src/new_trading_system/adapters/alpaca_paper.py`: Alpaca paper broker and market-data adapter
- `src/new_trading_system/strategies/legacy_iron_condor.py`: first extracted legacy options strategy plugin with profit/stop/DTE exits, duplicate-expiry blocking, and broken-structure alerts
- `apps/dashboard/index.html`: static operator dashboard for the generated summary JSON
- `var/worker.lock`: overlap protection so two worker runs cannot mutate the same paper state concurrently

Quick start:

- `python3 -m pip install -e ".[dev]"`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper --execute`
- `PYTHONPATH=src python3 -m new_trading_system.cli reconcile --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli verify --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker alpaca-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli verify --broker alpaca-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli dashboard`
- `pytest -q`

Worktree note:

- paper credentials stay in the git-ignored root `.env.paper.local`
- worktree checkouts automatically fall back to that root env file, so feature branches can verify Alpaca paper behavior without copying secrets into each worktree

Top-level layout:

- `apps/`: dashboard and operator-facing interfaces
- `services/`: platform runtime services
- `packages/`: reusable SDKs, schemas, and shared types
- `strategies/`: pluggable strategy families
- `schemas/`: versioned JSON contracts
- `infra/`: deployment and environment assets
- `tests/`: replay and integration verification harnesses

Documentation governance:

- `AGENTS.md` tells future LLM and engineering work to keep docs synchronized with the codebase.
