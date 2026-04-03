# Trading Loop System

This directory vendors and adapts the external `LOOP SYSTEM` into this repository so the platform can run persistent research and implementation cycles against `tasks/master-roadmap.md`.

## Purpose

The loop system is not the trading runtime. It is the project execution runtime.

It is used to:

- audit architectural drift
- implement backlog tasks
- review completed work
- keep project momentum going across many iterations

## Modes

- `./start.sh ../tasks/master-roadmap.md`
  - sequential loop, default agent
- `./start.sh ../tasks/master-roadmap.md --agent orchestrator`
  - full pipeline loop
- `./start.sh ../tasks/master-roadmap.md --swarm --backend codex`
  - parallel work when tasks are independent
- `python3 loop.py todo ../tasks/master-roadmap.md --backend codex --max-iter 5`
  - direct loop invocation

## Adaptation Notes

The original loop system was built around a UE5 workflow. In this repo it has been re-oriented around:

- trading-system architecture
- market-intelligence research
- strategy validation
- replay and risk verification

## Safety Rules

- The loop system must only act on explicit backlog items.
- It must use isolated git worktrees for implementation work.
- It must verify every claimed change with concrete commands.
- It must not promote anything to live trading on its own.
- It must not change hard risk policy without an explicit task.

## Main Files

- `loop.py`: persistent sequential executor
- `swarm.py`: parallel task executor
- `start.sh`: entrypoint wrapper
- `decision-context.md`: owner preferences and project priorities
- `audit.agent.md`: architecture and risk drift scanner
- `todo.agent.md`: implementation worker
- `completed-review.agent.md`: review and verification agent
- `orchestrator.agent.md`: audit → implement → review coordinator
- `decision-oracle.agent.md`: resolves irreversible ambiguities only

