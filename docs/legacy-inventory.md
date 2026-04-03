# Legacy Inventory

Last updated: 2026-04-03

This document is the concrete extraction inventory for the legacy `trading` repo.

It exists so we do not migrate by vague memory.

## Bucket Meanings

- `Extract`: preserve most of the behavior with only enough translation to fit the new platform contracts
- `Redesign`: keep the idea, but rebuild it cleanly
- `Reference-Only`: keep as design input or research context, not runtime code
- `Discard`: do not migrate into the new trading runtime

## Strategies

| Legacy Asset | Current Role In Old Repo | New Treatment | Planned New Home |
| --- | --- | --- | --- |
| `src/strategies/iron_condor/*` | core options strategy modules | `Extract + Redesign` | `src/new_trading_system/strategies/legacy_iron_condor.py` and future `strategies/options-trading/` package |
| `scripts/iron_condor_trader.py` | direct entry script for iron condors | `Extract + Redesign` | strategy runtime + options strategy plugin |
| `scripts/manage_iron_condor_positions.py` | lifecycle and exit management | `Extract + Redesign` | strategy plugin + position-management services |
| `scripts/iron_condor_scanner.py` | opportunity scan logic | `Extract` | future strategy signal layer |
| `scripts/iron_condor_guardian.py` | monitoring and protection logic | `Redesign` | risk engine + worker operator flows |
| `src/strategies/vix_mean_reversion.py` | regime timing concept | `Extract` | future market-intelligence layer and options signal layer |
| `src/strategies/momentum_strategy.py` | directional equity momentum logic | `Reference-Only` first | future strategy family after replay lab exists |
| `src/strategies/legacy_momentum.py` | older momentum implementation | `Reference-Only` | historical comparison input only |
| `src/strategies/rule_one_options.py` | options framework idea | `Reference-Only` then `Redesign` | future options strategy family |
| `scripts/rule_one_trader.py` | script wrapper around Rule One behavior | `Reference-Only` | only after core replay lab is real |
| `src/strategies/reit_strategy.py` | REIT-specific strategy | `Reference-Only` | future narrow strategy family if thesis survives replay |
| `src/strategies/core_strategy.py` | mixed strategy/runtime abstraction | `Discard` as runtime code | historical reference only |
| `src/strategies/registry.py` | registry idea | `Redesign` | `src/new_trading_system/services/control_plane.py` |

## Script Families

The old repo has 150+ Python and shell scripts. We should not port them one by one.

### Extract Or Redesign Into Product CLIs

| Family | Representative Legacy Files | Treatment | New Product Surface |
| --- | --- | --- | --- |
| trading execution | `execute_options_trade.py`, `execute_credit_spread.py`, `simple_daily_trader.py`, `autonomous_trader.py` | `Redesign` | `new_trading_system.cli worker` |
| position management | `manage_positions.py`, `close_positions.py`, `close_all_options.py`, `close_all_positions.py`, `close_excess_spreads.py` | `Redesign` | `new_trading_system.cli ops` and strategy lifecycle services |
| broker sync and reconciliation | `sync_alpaca_state.py`, `sync_trades_from_alpaca.py`, `sync_closed_positions.py`, `generate_alpaca_snapshot.py` | `Redesign` | `new_trading_system.cli reconcile` |
| verification and pre-trade safety | `pre_trade_checklist.py`, `verify_orders.py`, `verify_positions.py`, `verify_trade_execution.py`, `verify_pl_sanity.py`, `verify_stops_in_place.py`, `check_duplicate_execution.py`, `validate_ticker_whitelist.py` | `Redesign` | `new_trading_system.cli verify` |
| stale-order and cleanup protection | `cancel_stale_orders.py`, `cancel_and_protect.py`, `liquidate_losing_positions.py`, `emergency_position_cleanup.py` | `Redesign` | risk engine, execution engine, and operator CLI |
| health and operator status | `health_monitor.py`, `system_health_check.py`, `pre_market_health_check.py`, `workflow_health_monitor.py`, `monitor_trade_activity.py` | `Redesign` | operator dashboard and health monitor service |
| analytics and attribution | `build_sqlite_analytics.py`, `calculate_win_rate.py`, `generate_profit_readiness_scorecard.py`, `update_performance_log.py` | `Redesign` | research lab + dashboard read models |
| backtests and evaluation | `run_core_strategy_reference_backtest.py`, `fetch_100k_trade_history.py`, `compare_100k_vs_5k.py` | `Redesign` | replay lab |
| learning and feedback | `historical_learning_backfill.py`, `train_from_feedback.py`, `collect_unsloth_dataset.py`, `evaluate_rag.py` | `Reference-Only` first | future learning services after replay lab maturity |
| market-intelligence inputs | `update_ai_credit_stress_signal.py`, `update_ai_cycle_signal.py`, `update_usd_macro_sentiment_signal.py`, `check_north_star_probability.py`, `build_north_star_blocker_report.py` | `Extract + Redesign` | market-intelligence services and dashboards |

### Keep As Reference Only

| Family | Representative Legacy Files | Why |
| --- | --- | --- |
| RAG and memory enrichment | `record_account_to_rag.py`, `sync_trades_to_rag.py`, `vectorize_rag_knowledge.py`, `build_rag_query_index.py` | good ideas, but tightly mixed with the old operating model |
| autonomous loop experiments | `ralph_loop.py`, `tars_autopilot.sh`, `continuous_devloop.sh`, `devloop_*` | useful process ideas, but not part of the trading runtime |
| browser and screenshot helpers | `capture_trading_screenshots.py`, `run_browser_automation_pilot.py` | useful for operations later, not core engine now |

### Discard Or Move Out Of Runtime Scope

| Family | Representative Legacy Files | Why |
| --- | --- | --- |
| publishing and SEO | `generate_blog_post.py`, `publish_twitter.py`, `publish_linkedin.py`, `cross_publish.py`, `seo_health_check.py`, `submit_to_search_console.py` | valuable in a content system, not the trading platform runtime |
| repo maintenance one-offs | `cleanup_old_files.py`, `fix_blog_posts_for_lint.py`, `update_docs_index.py`, `find_uncovered_modules.py` | not part of the runtime platform |
| compliance or marketing wrappers unrelated to platform runtime | `ai_disclosure.py`, `compliance_audit.py`, `check_ai_discoverability.py` | separate concern from trading execution |

## Workflow Families

Legacy workflow count: `90`

### Keep The Idea, But Shrink The Surface

| Workflow Family | Representative Files | Treatment | New Direction |
| --- | --- | --- | --- |
| trading runtime orchestration | `daily-trading.yml`, `manage-iron-condor-positions.yml`, `iron-condor-autonomous.yml`, `iron-condor-scan.yml`, `position-monitor.yml` | `Redesign` | move logic into worker and services, keep only thin schedulers if needed |
| emergency controls | `emergency-close-options.yml`, `emergency-position-cleanup.yml`, `emergency-protection.yml`, `run-liquidation.yml`, `force-close-position.yml` | `Redesign` | operator console + controlled emergency CLI |
| broker diagnostics and sync | `diagnose-alpaca-connection.yml`, `sync-alpaca-status.yml`, `verify-trade-execution.yml`, `cancel-stale-orders.yml` | `Redesign` | reconcile and verify commands plus health monitor |
| CI and validation | `ci.yml`, `codeql.yml`, `validate-documentation.yml`, `verify-web-pages.yml`, `secrets-scan.yml` | `Extract` | keep as CI/CD workflows |
| backtests and research | `off-market-backtest.yml`, `offline-evals.yml`, `weekend-learning.yml`, `weekend-research.yml`, `analyze-100k-history.yml` | `Redesign` | replay lab and research pipeline jobs |
| dashboard/docs publish | `deploy-pages.yml`, `update-progress-dashboard.yml`, `update-wiki.yml` | `Redesign` | publish only generated docs and dashboard read models that reflect repo truth |

### Reference Only

| Workflow Family | Representative Files | Why |
| --- | --- | --- |
| agentic experimentation | `swarm-orchestration.yml`, `claude-agent-utility.yml`, `ralph-loop-ai.yml`, `ralph-mode-cto.yml` | useful process history, not the clean runtime baseline |
| niche trading ops experiments | `detect-contract-accumulation.yml`, `force-iron-condor.yml`, `close-orphan-position.yml` | keep as ideas while we rebuild clean operator flows |

### Discard Or Separate

| Workflow Family | Representative Files | Why |
| --- | --- | --- |
| content and blogging | `daily-blog-post.yml`, `cross-publish-post.yml`, `phil-town-ingestion.yml`, `rlhf-blog-publisher.yml` | not part of the trading runtime |
| one-off maintenance glue | `one-time-secret-update.yml`, `dependabot-automerge.yml`, `merge-branch.yml` | repo hygiene only, not part of the migration program |

## Best Legacy Ideas Worth Preserving

- Hard pre-trade gates that separate opening-order checks from closing-order safety.
- Strong verification culture through sync, verify, and health-check routines.
- Strategy-specific lifecycle management instead of treating all positions as generic.
- Options-specific regime thinking through VIX, IV, and structure constraints.
- Research and attribution habits that try to connect decisions to outcomes.
- Operator visibility through dashboards, snapshots, and readiness scorecards.

## Migration Rule

If a legacy item is useful but cannot fit the new boundaries below, redesign it instead of copying it:

- strategies emit intents but do not talk to brokers
- broker adapters translate and reconcile but do not own strategy logic
- the ledger owns PnL truth
- workflows do not contain business logic that belongs in services
- runtime state stays out of git

