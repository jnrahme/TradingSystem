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
- `src/new_trading_system/strategies/legacy_iron_condor.py`: first extracted legacy options strategy plugin with profit/stop/DTE exits, next-available expiry discovery inside the configured DTE window, a basic VIX regime gate when volatility data is available, duplicate-expiry blocking, and broken-structure alerts
- `apps/dashboard/index.html`: static operator dashboard for the generated summary JSON
- `var/worker.lock`: overlap protection so two worker runs cannot mutate the same paper state concurrently
- named runtime accounts can isolate their own state DB, strategy state, worker lock, internal paper state, dashboard summary, and paper-broker credentials via `--account <id>` plus `NTS_ACCOUNT_<ID>_*` env keys
- `run-accounts` can execute several named accounts sequentially in one command while preserving per-account isolation
- `run-loop` and `run-accounts` can now stay up continuously with `--forever` for unattended paper cycling
- `scorecard` turns the canonical ledger into a paper-readiness report so strategy claims stay tied to observed evidence
- `replay` now runs a first synthetic internal-paper scenario set for the legacy iron-condor strategy so replay coverage starts with deterministic execution evidence instead of historical claims we do not have yet
- `replay --scenario-set historical-bars` now runs a first honest historical backtest using real SPY daily bars plus modeled option pricing, so the repo can produce bar-driven profitability evidence instead of only synthetic scenarios
- the historical-bars replay now bounds exits to the contract expiry window and skips trades when the future bar data is insufficient, instead of allowing impossible post-expiry holds across data gaps
- the historical-bars replay now also respects the live strategy's `max_open_structures` and duplicate-expiry constraints, so long-window replay samples are smaller but better aligned with the real runtime behavior
- replay reports now persist under `var/replay/`, and `scorecard` consumes them so replay evidence is cumulative instead of session-local
- `promotion` now evaluates saved replay evidence plus paper scorecard evidence against strategy-defined thresholds and explains exactly why a strategy is or is not ready to advance
- `autonomous-runner` now adds a market-hours supervisor with a halt file, runtime status/heartbeat files, sequential multi-account execution, and optional post-cycle reconcile/verify hooks
- `autonomous-status`, `autonomous-halt`, and `autonomous-resume` now expose first-class runtime controls around that supervisor without changing trading logic
- when the legacy `trading` repo is present as a sibling checkout, `scorecard` and `promotion` now surface its closed-trade ledger as explicitly labeled legacy reference evidence rather than silently counting it as current-system proof

Quick start:

- `python3 -m pip install -e ".[dev]"`
- `bash scripts/verify.sh`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-loop --account primary --broker internal-paper --execute --forever --interval-seconds 60`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --account primary --broker internal-paper --execute`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-accounts --account primary --account swing-two --broker internal-paper --execute`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-accounts --account primary --account swing-two --broker internal-paper --execute --forever --interval-seconds 60`
- `PYTHONPATH=src python3 -m new_trading_system.cli autonomous-runner --account primary --broker internal-paper --execute --forever --interval-seconds 300 --verify-after-cycle`
- `PYTHONPATH=src python3 -m new_trading_system.cli autonomous-status`
- `PYTHONPATH=src python3 -m new_trading_system.cli autonomous-halt --reason "manual operator halt"`
- `PYTHONPATH=src python3 -m new_trading_system.cli autonomous-resume`
- `PYTHONPATH=src python3 -m new_trading_system.cli scorecard --account primary --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli replay --strategy legacy-iron-condor`
- `PYTHONPATH=src python3 -m new_trading_system.cli replay --scenario-set historical-bars --days 90 --strategy legacy-iron-condor`
- `PYTHONPATH=src python3 -m new_trading_system.cli promotion --account primary --broker internal-paper --strategy legacy-iron-condor`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker internal-paper --execute`
- `PYTHONPATH=src python3 -m new_trading_system.cli reconcile --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli verify --broker internal-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli run-once --broker alpaca-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli verify --account swing-two --broker alpaca-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli verify --broker alpaca-paper`
- `PYTHONPATH=src python3 -m new_trading_system.cli dashboard`
- `pytest -q`

Worktree note:

- paper credentials stay in the git-ignored root `.env.paper.local`
- worktree checkouts automatically fall back to that root env file, so feature branches can verify Alpaca paper behavior without copying secrets into each worktree

Multi-account note:

- the default runtime account keeps the original paths and commands unchanged
- named accounts use `--account <id>` and isolate state under `var/accounts/<id>/`
- named dashboard summaries are written to `apps/dashboard/data/accounts/<id>.json`
- fleet runs also update `apps/dashboard/data/accounts/summary.json` with the latest cross-account iteration summary
- named broker credentials can be supplied with `NTS_ACCOUNT_<ID>_BROKER`, `NTS_ACCOUNT_<ID>_ALPACA_PAPER_API_KEY`, and `NTS_ACCOUNT_<ID>_ALPACA_PAPER_API_SECRET`
- `run-accounts` runs named accounts sequentially in one process and respects each account's own worker lock and state paths
- add `--forever` to `run-loop` or `run-accounts` when you want the process to keep cycling until you stop it
- replay reports are written under `var/replay/` and show up in `scorecard` once they exist for a strategy
- `historical-bars` replay uses real historical SPY bars from Alpaca, Black-Scholes option pricing, and a realized-volatility proxy for the VIX gate; it is stronger than the demo replay, but still not a quote-by-quote options-chain replay
- the live Alpaca paper path now uses the same realized-volatility proxy when direct `VIX` quotes are unavailable, so the entry filter stays active instead of silently degrading to a warning-only path
- `promotion` is an evidence gate for advancing strategy stages; it is not a profitability guarantee and it does not bypass manual live approval
- `autonomous-runner` honors `var/runtime/AUTONOMOUS_HALTED`, writes `var/runtime/autonomous_status_latest.json`, `var/runtime/autonomous_status_history.jsonl`, and `var/runtime/autonomous_heartbeat.json`, and has a service-wrapper example at `infra/systemd/new-trading-system-autonomous.service.example`
- `autonomous-status` reads those runtime artifacts, while `autonomous-halt` and `autonomous-resume` manage the halt file directly for operator control
- the current legacy iron condor runtime now allows up to **8** concurrent structures, giving the runtime room for a very near weekly expiry rung without degrading the constrained replay profile
- the live DTE entry window now spans **11-52 DTE**, matching the enforced rule that new entries stay outside the 10-DTE forced-exit zone
- the live risk engine now merges broker-backed same-day order history into its intraday structure/fill guardrails, so repeated entries cannot bypass the policy just because the local ledger started fresh
- the live weekly ladder now permits up to **8 same-day structures**, with cumulative-risk limits still providing the primary exposure cap
- the current iron condor minimum credit floor is now **0.40**, which allows the near-expiry weekly rung without degrading the constrained replay profile
- the current iron condor take-profit target is now **2.5%**, chosen because it preserved the clean constrained replay profile while shortening holding time further and bringing the live paper book closer to real exits
- the live DTE exit threshold is now **10 DTE**, which left the constrained replay unchanged while allowing the near-expiry live condor to qualify for exit sooner
- live reconciliation now tolerates tiny option mark drift (for example a $1 market-value difference on a single contract) so harmless quote jitter does not mark the autonomous runtime degraded
- legacy trade evidence, when found at the sibling `trading/data/trades.json`, is shown separately as calibration/reference only and does not satisfy current-system readiness checks by itself

Verification note:

- `.github/workflows/ci.yml` now runs `bash scripts/verify.sh` on pushes and pull requests
- the verification script checks patch hygiene, compiles Python, parses schema JSON files, runs `pytest -q`, and exercises the internal paper worker plus reconcile and verify commands

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
