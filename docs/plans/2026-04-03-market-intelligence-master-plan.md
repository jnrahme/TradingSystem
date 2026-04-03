# Market Intelligence Master Plan

Date: April 3, 2026

## Why This Plan Exists

The goal is not to build a bot that randomly trades more often.

The goal is to build a system that:

1. Learns what tends to move markets up or down.
2. Converts that understanding into testable strategy rules.
3. Uses AI where AI is strong.
4. Uses hard risk and verification where AI is weak.
5. Compounds our knowledge, tooling, and capital over time.

The biggest trap is trying to "account for everything" with one giant black-box model. Markets do not work like that. We need a layered system that explains a market move through a stack of drivers, then chooses a trade expression that fits the regime.

## Hard Truths

### Hard truth 1: we cannot predict everything

No system will perfectly model every news event, every emotion swing, every liquidity shock, or every regime break. The right design is not omniscience. The right design is:

- better inputs
- better regime classification
- better trade selection
- better sizing
- better exits
- better risk control
- better learning loops

### Hard truth 2: the current `trading` repo contains useful lessons, not a final platform

The current repo taught us what not to repeat:

- strategy logic exists in multiple places
- workflow files and scripts own too much runtime behavior
- file-based state drifts over time
- risk logic is partially bypassed by direct script flows
- "intelligence" is mostly advisory on top of rules
- there is not enough closed-trade data to justify adaptive confidence claims

This new repo must absorb those lessons and turn them into architecture rules.

### Hard truth 3: the first profitable path should be simple enough to learn

Because we are still learning trading, the first target should not be the most complicated instrument. It should be the most understandable, liquid, and testable market arena.

## What Actually Moves Markets

We should model market movement as a layered stack, not a single cause.

### Layer 1: Macro and policy

Examples:

- Federal Reserve rate decisions and guidance
- inflation data
- labor data
- GDP and growth surprises
- Treasury liquidity and auction stress
- geopolitical shocks

These set the background regime: risk-on, risk-off, inflation scare, growth scare, easing cycle, tightening pause, and so on.

### Layer 2: Cross-asset confirmation

Examples:

- SPY / QQQ direction
- Treasury yields
- dollar strength
- gold behavior
- credit spreads
- Bitcoin and major crypto risk appetite
- volatility indexes and term structure

This tells us whether a move is isolated or broad-based.

### Layer 3: Event flow

Examples:

- earnings
- guidance cuts
- SEC filings
- M&A
- product launches
- analyst revisions
- sector-specific news

This is where narrative and surprise matter most.

### Layer 4: Positioning and sentiment

Examples:

- options flows
- dealer positioning proxies
- retail sentiment
- social/media trend intensity
- crowding
- short interest

This tells us when the move is already crowded or when an unexpected move can squeeze hard.

### Layer 5: Market internals

Examples:

- breadth
- advance/decline
- volume profile
- realized volatility
- implied volatility
- order-book imbalance
- spreads
- opening gap behavior

This tells us whether the tape supports the narrative.

### Layer 6: Mathematical structure

Examples:

- momentum
- mean reversion
- trend persistence
- volatility clustering
- seasonality
- correlation regime changes
- support/resistance behavior

This is where formulas belong. Formulas should describe repeatable structure after the higher-level context is understood.

## Best Organic Growth Path

### Recommendation

The first learning and deployment wedge should be:

**broad-market regime trading on a small set of liquid instruments, then options as the expression layer after the regime engine proves itself.**

That means the platform should begin with a tight universe such as:

- SPY
- QQQ
- IWM
- TLT
- GLD
- BTC

This is the best organic growth path because:

- it gives us fewer symbols to understand deeply
- those symbols reflect the highest-level "market up or down" question
- they have stronger data quality and cleaner liquidity than penny names
- they are easier to explain and backtest than thousands of low-quality tickers
- once the market-state engine works here, it can be reused for options and crypto

### Why not penny stocks first

Penny and microcap names are exactly where manipulation, poor disclosure, low liquidity, spread blowouts, and halt risk are worst. They may look attractive because the moves are dramatic, but they are a terrible first teacher.

### Why not pure options first

Options are powerful, but they add another full layer of complexity:

- Greeks
- IV/RV relationships
- skew
- expiration effects
- assignment risk
- multi-leg execution

We should still build options into the platform early because the existing `trading` repo gives us a head start there. But the first real "why is the market moving" engine should learn on the underlying market first.

## Recommended Strategy Ladder

### Stage 1: Market Intelligence Only

Output:

- daily market regime summary
- event map
- risk map
- probability-weighted directional bias
- watchlist of tradeable regimes

No live capital. This stage learns to explain the market.

### Stage 2: Broad ETF Directional and Swing Strategies

Examples:

- trend-following on index ETFs
- mean-reversion after volatility spikes
- event-driven swing entries around macro calendars
- breadth-confirmed breakout systems

This stage teaches position sizing, entries, exits, and attribution on simple instruments.

### Stage 3: Defined-Risk Options Strategies

Examples:

- vertical spreads
- iron condors only when regime and vol structure agree
- event-aware premium selling
- convex hedges during stress regimes

This stage reuses learnings from the old `trading` repo, but under better architecture.

### Stage 4: Crypto Strategies

Examples:

- major-pair trend / mean-reversion
- basis and carry opportunities
- event-driven volatility response

Only after 24x7 controls are solid.

### Stage 5: Penny and Microcap Experimental Layer

Only after fraud filters, catalyst verification, halt logic, spread controls, and low-float risk controls are proven.

## What AI Should Do

AI is powerful for compression, ranking, labeling, and hypothesis generation. It is weak when allowed to trade without controls.

### AI should do these jobs

- summarize macro and company news
- classify whether news is likely positive, negative, or neutral for specific assets
- cluster similar regimes
- extract structured signals from unstructured text
- produce market narratives for operator review
- generate candidate hypotheses for backtesting
- rank potential setups inside a rules-based envelope
- write post-trade attributions
- power research copilots and internal analysts

### AI should not do these jobs alone

- direct broker order placement
- unrestricted position sizing
- changing hard risk limits
- self-promoting from paper to live
- overriding kill switches

## System Design for "Accounting for Everything"

We should not literally try to ingest everything equally. We should build a ranking system for inputs.

### Core engine

1. `Market State Engine`
   - builds a structured view of macro, cross-asset, volatility, breadth, and liquidity
2. `Event Intelligence Engine`
   - ingests news, earnings, filings, calendars, and social narrative
3. `Feature Store`
   - stores normalized features and derived factors
4. `Strategy Runtime`
   - loads strategies as plugins and lets them consume approved context
5. `Risk Engine`
   - approves, scales, or blocks intents
6. `Execution Engine`
   - routes to broker adapters or internal paper simulation
7. `Ledger`
   - source of truth for PnL, exposure, fills, fees, and slippage
8. `Learning Loop`
   - evaluates strategies, policies, prompts, and trade outcomes

### Key principle

The market-intelligence engine and the trade-expression engine are separate.

That means:

- the system can be right about regime and still choose no trade
- the system can detect uncertainty and shrink risk
- different strategies can consume the same market-state output
- we can compare whether the weakness is in the forecast, the expression, or the execution

## Existing Tools We Should Leverage

### Data and market infrastructure

- Broker data for early prototypes when cheap and sufficient
- Better normalized market data when the platform needs consistency and scale
- Official macro, Fed, SEC, and company sources for high-value event ingestion

### AI infrastructure

- OpenAI Responses API for agentic workflows and tool-using research loops
- embeddings for retrieval over internal journals, filings, transcripts, and post-trade notes
- structured outputs for turning noisy text into typed events and factors
- evals for measuring whether prompts, classifiers, and assistants are improving

### Trading and research references

- LEAN / QuantConnect as a reference architecture and possible research harness
- Freqtrade as a crypto experimentation reference
- backtesting libraries for rapid hypothesis tests

These should be leveraged selectively. We are not outsourcing the core platform to them.

## Broker and Venue Recommendation

Do not tie the system to one broker.

### Recommended venue roles

- `Alpaca`: early development and paper path for equities, options, and crypto
- `IBKR`: broad multi-asset production adapter on the non-crypto side
- `Coinbase`: primary crypto adapter
- `Tradier` or `tastytrade`: options-specialist adapter if we need deeper options workflows

### Critical rule

Broker paper environments are useful but not the truth layer. We must own an internal simulator and replay engine.

## Data Stack Recommendation

### Phase 1

- official macro calendars and releases
- broker market data for low-cost prototyping
- basic news ingestion
- internal journals and trade logs

### Phase 2

- normalized historical OHLCV
- options chain history for selected underlyings
- cross-asset regime inputs
- news and filings archive

### Phase 3

- intraday event labeling
- sentiment and narrative clustering
- higher-resolution market microstructure where justified

## AI Stack Recommendation

### First AI systems

1. `Macro Narrator`
   - summarizes the daily regime
2. `Event Extractor`
   - converts news into typed records
3. `Regime Classifier`
   - labels environment as trend, panic, squeeze, grind, mean-revert, event-risk, and so on
4. `Strategy Copilot`
   - proposes candidate trades inside strict policy bounds
5. `Post-Trade Analyst`
   - explains winners, losers, drift, and missed opportunities

### Later AI systems

- parameter policy tuning
- anomaly detection
- research agent swarm
- prompt / model registry and evaluation harness

## Loop System Integration

The `LOOP SYSTEM` is useful as the execution shell for continuous work, but it needs to become trading-specific.

### What to reuse

- persistent loop runner
- swarm runner
- decision oracle pattern
- worktree isolation
- disk-based handoff state

### What to replace

- UE5-specific prompts
- game-specific build/test assumptions
- audit criteria
- completed-review criteria

### New loop roles

- `audit`: scan the platform and strategy code for architectural drift, missing tests, and broken boundaries
- `todo`: implement the next backlog item and verify it
- `completed-review`: review completed work for correctness, risk, and adherence to the plan
- `orchestrator`: drive the backlog through audit → implement → review

## Lessons to Carry Forward from the Old Trading Repo

1. One canonical strategy contract.
2. One canonical ledger and state model.
3. One canonical risk path.
4. No strategy code should directly talk to broker payloads.
5. No learning claim without enough samples.
6. No file-based state sprawl.
7. No workflow file should secretly become the runtime brain.

## Success Metrics

### System metrics

- replay determinism
- data freshness
- reconciliation accuracy
- order lifecycle visibility
- mean time to detect drift
- mean time to recover from broker/data incident

### Strategy metrics

- expectancy
- max drawdown
- risk-adjusted return
- slippage versus model
- live-versus-paper drift
- regime-specific performance
- stability of edge across market conditions

### Intelligence metrics

- event classification accuracy
- prompt eval scores
- regime-label consistency
- whether the AI improves trade selection over baseline rules

## What We Should Build First

### Immediate focus

1. trading-specific loop system inside this repo
2. execution backlog
3. market-intelligence schemas
4. internal paper simulation plan
5. daily market-note generation
6. first broad-market research strategy

### First strategy family

The first actual strategy family should be:

**broad-market ETF regime trading**

The first advanced strategy family after that should be:

**defined-risk index and ETF options**

## Near-Term Research Questions

- Which regime labels best predict next-session or next-week behavior?
- Which macro events matter most for our chosen universe?
- Which features retain signal out of sample?
- How much value does AI add beyond structured rules?
- When does options expression improve returns enough to justify complexity?

## 90-Day Build Sequence

### Days 1-14

- set up repo contracts
- import and adapt loop system
- write backlog
- wire CI checks
- define schemas for market state, event, insight, order intent, and trade attribution

### Days 15-30

- build daily market intelligence pipeline
- ingest official macro calendar and core market data
- generate daily market note and regime report
- store everything in structured form

### Days 31-45

- build replay harness for broad ETFs
- test baseline momentum and mean-reversion systems
- create evaluation dashboards

### Days 46-60

- add broker paper adapter
- add internal simulator
- compare live paper behavior versus internal simulation

### Days 61-90

- select first production candidate
- run shadow / paper validation
- implement risk limits and promotion rules
- start micro-capital canary only if evidence supports it

## Final Recommendation

If we want this platform to actually compound into something real, we should optimize for:

- understanding first
- clean architecture second
- verified strategies third
- capital scaling last

The fastest path to "a lot of money" is not forcing complexity. It is building a machine that learns the market better every week, preserves what it learns, tests that learning honestly, and expresses it through the simplest instrument that fits the edge.

## References

- [Federal Reserve FOMC calendars and implementation notes](https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm)
- [Cboe research on put-writing strategies](https://cdn.cboe.com/resources/education/research_publications/PutWriteCBOE19_v14_by_Prof_Oleg_Bondarenko_as_of_June_14.pdf)
- [Cboe state of the options industry](https://www.cboe.com/insights/posts/the-state-of-the-options-industry-2025/)
- [Alpaca Trading API docs](https://docs.alpaca.markets/docs/api-references/trading-api/)
- [Alpaca options trading docs](https://docs.alpaca.markets/v1.3/docs/options-trading)
- [Interactive Brokers Campus API docs](https://www.interactivebrokers.com/campus/ibkr-api-page/twsapi-doc/)
- [Coinbase Advanced Trade docs](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/guides/sdk-rest-api)
- [Coinbase derivatives market hours](https://docs.cdp.coinbase.com/derivatives/introduction/market-hours)
- [Tradier trading docs](https://docs.tradier.com/docs/trading)
- [TradeStation SIM vs LIVE docs](https://api.tradestation.com/docs/fundamentals/sim-vs-live/)
- [tastytrade API overview](https://developer.tastytrade.com/api-overview/)
- [OpenAI evals guide](https://platform.openai.com/docs/guides/evals/datasets)
- [QuantConnect / LEAN docs](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/algorithm-engine)
- [Freqtrade docs](https://www.freqtrade.io/en/stable/)
