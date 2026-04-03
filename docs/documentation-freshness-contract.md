# Documentation Freshness Contract

This project treats documentation as part of the runtime surface, not as a side note.

## Goal

Any person or LLM should be able to open the repo and answer three questions truthfully:

1. What is real today?
2. What is planned but not built yet?
3. Where does each moving piece live?

## Required Documents

- `README.md`
  - top-level capabilities
  - entrypoints
  - quick-start commands
- `docs/current-state.md`
  - what exists now
  - what is missing
  - what is verified
- `docs/legacy-inventory.md`
  - concrete extraction and discard decisions for legacy assets
- `docs/legacy-extraction-portal.html`
  - human-friendly published architecture and migration map
- `docs/plans/*.md`
  - detailed plans for major work streams
- `tasks/master-roadmap.md`
  - backlog truth
- `AGENTS.md`
  - future LLM behavior and documentation rules

## Update Triggers

Update the docs in the same change when any of the following happen:

- a new strategy is added or removed
- a broker adapter is added or materially changes behavior
- the worker, risk path, execution path, or ledger changes
- a dashboard or operator flow changes
- a migration phase starts, completes, or changes shape
- a command, setup step, or verification flow changes

## Minimum Update Matrix

| If this changes | Update these docs |
| --- | --- |
| CLI commands or setup | `README.md`, `docs/current-state.md` |
| Architecture or boundaries | `docs/current-state.md`, `docs/legacy-inventory.md`, `docs/legacy-extraction-portal.html`, relevant plan |
| Migration status | `docs/current-state.md`, `tasks/master-roadmap.md`, portal page |
| LLM/documentation rules | `AGENTS.md`, this file, loop context if relevant |
| New extraction decision | `docs/legacy-inventory.md`, relevant plan, roadmap, portal page |

## Verification

Before saying docs are updated:

- run `git diff --check`
- read the changed docs back
- if an HTML page changed, load it in a browser or local server and confirm it renders
- if commands changed, run them

## Non-Negotiable Rule

If the implementation and documentation disagree, the work is not done.
