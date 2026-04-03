#!/bin/bash
# ============================================================================
# START — Single entry point for the Loop System
# ============================================================================
#
# Usage:
#   ./start.sh <task-file.md>                        # Sequential (default: todo agent)
#   ./start.sh <task-file.md> --agent orchestrator   # Use orchestrator agent
#   ./start.sh <task-file.md> --agent audit          # Use audit agent
#   ./start.sh <task-file.md> --backend codex        # Force backend
#   ./start.sh <task-file.md> --swarm                # Parallel multi-agent
#   ./start.sh <task-file.md> --swarm --backend codex
#   ./start.sh <task-file.md> --dry-run              # Preview execution plan
#
# ============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'

# ── Parse mode ────────────────────────────────────────────────────────────

MODE="loop"
TASK_FILE=""
AGENT="todo"    # Fix #10: configurable, default to todo
BACKEND=""
EXTRA_ARGS=()

i=0
args=("$@")
while [ $i -lt ${#args[@]} ]; do
    arg="${args[$i]}"
    case "$arg" in
        --swarm)  MODE="swarm" ;;
        --agent)
            # Fix #10: accept --agent flag
            i=$((i + 1))
            AGENT="${args[$i]}"
            ;;
        --backend)
            i=$((i + 1))
            BACKEND="${args[$i]}"
            ;;
        --help|-h)
            echo -e "${BOLD}Loop System — Start${NC}"
            echo ""
            echo "Usage:"
            echo "  ./start.sh <task-file.md>                        # Sequential (todo agent)"
            echo "  ./start.sh <task-file.md> --agent orchestrator   # Full pipeline"
            echo "  ./start.sh <task-file.md> --agent audit          # Audit only"
            echo "  ./start.sh <task-file.md> --backend codex        # Force backend"
            echo "  ./start.sh <task-file.md> --swarm                # Parallel swarm"
            echo "  ./start.sh <task-file.md> --swarm --backend codex"
            echo "  ./start.sh <task-file.md> --dry-run              # Preview plan"
            echo ""
            echo "Agents: todo | audit | completed-review | orchestrator"
            echo "Backends: codex | claude | opencode"
            echo ""
            echo "Sequential loop: One task at a time, never stops, auto-resumes."
            echo "Parallel swarm:  Analyzes dependencies, spawns N agents at once."
            echo ""
            echo "Fill out decision-context.md so agents make decisions like you."
            exit 0
            ;;
        *)
            if [ -z "$TASK_FILE" ] && [[ ! "$arg" == --* ]]; then
                TASK_FILE="$arg"
            else
                EXTRA_ARGS+=("$arg")
            fi
            ;;
    esac
    i=$((i + 1))
done

if [ -z "$TASK_FILE" ]; then
    echo -e "${RED}Error: No task file specified.${NC}"
    echo "Usage: ./start.sh <task-file.md> [--agent NAME] [--swarm] [options]"
    exit 1
fi

if [ ! -f "$TASK_FILE" ]; then
    echo -e "${RED}Error: Task file not found: $TASK_FILE${NC}"
    exit 1
fi

# ── Pre-flight checks ────────────────────────────────────────────────────

echo -e "${BOLD}Pre-flight checks...${NC}"

check_backend() {
    local cmd="$1"
    if command -v "$cmd" &>/dev/null; then
        echo -e "  ${GREEN}✓${NC} $cmd found"
        return 0
    else
        echo -e "  ${RED}✗${NC} $cmd not found"
        return 1
    fi
}

BACKEND_OK=false
AVAILABLE_BACKENDS=()
check_backend "codex" && { BACKEND_OK=true; AVAILABLE_BACKENDS+=("codex"); } || true
check_backend "claude" && { BACKEND_OK=true; AVAILABLE_BACKENDS+=("claude"); } || true
check_backend "opencode" && { BACKEND_OK=true; AVAILABLE_BACKENDS+=("opencode"); } || true

if [ "$BACKEND_OK" = false ]; then
    echo -e "${RED}No LLM backend found. Install Claude Code, Codex, or OpenCode.${NC}"
    exit 1
fi

if [ -z "$BACKEND" ]; then
    BACKEND="${AVAILABLE_BACKENDS[0]}"
fi

echo -e "  ${GREEN}✓${NC} selected backend: ${BACKEND}"

# Check decision context — look for template markers like "[e.g." not just "- ["
if [ -f "$SCRIPT_DIR/decision-context.md" ]; then
    if grep -q '\[e\.g\.' "$SCRIPT_DIR/decision-context.md"; then
        echo -e "  ${CYAN}⚠${NC}  decision-context.md still has template examples"
        echo -e "     Fill it out so agents make decisions like you!"
    else
        echo -e "  ${GREEN}✓${NC} decision-context.md configured"
    fi
else
    echo -e "  ${CYAN}⚠${NC}  No decision-context.md — agents will use generic defaults"
fi

# Count tasks
REMAINING=$(grep -c '^- \[ \]' "$TASK_FILE" 2>/dev/null || true)
COMPLETED=$(grep -ci '^- \[x\]' "$TASK_FILE" 2>/dev/null || true)
BLOCKED=$(grep -c '^- \[\?\]' "$TASK_FILE" 2>/dev/null || true)
REMAINING=${REMAINING:-0}
COMPLETED=${COMPLETED:-0}
BLOCKED=${BLOCKED:-0}
echo -e "  ${GREEN}✓${NC} $REMAINING remaining, $COMPLETED done, $BLOCKED blocked"

echo ""

# ── Launch ────────────────────────────────────────────────────────────────

if [ "$MODE" = "swarm" ]; then
    echo -e "${BOLD}Launching SWARM (parallel multi-agent)...${NC}"
    exec python3 "$SCRIPT_DIR/swarm.py" "$TASK_FILE" --backend "$BACKEND" "${EXTRA_ARGS[@]}"
else
    echo -e "${BOLD}Launching LOOP (${AGENT} agent, sequential, persistent)...${NC}"
    # Fix #10: pass selected agent instead of hardcoded "todo"
    exec python3 "$SCRIPT_DIR/loop.py" "$AGENT" "$TASK_FILE" --backend "$BACKEND" "${EXTRA_ARGS[@]}"
fi
