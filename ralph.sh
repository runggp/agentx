#!/bin/bash
# Ralph - Autonomous development loop via Docker
# Usage: ./ralph.sh [plan] [max_iterations]
#
# Auth (Claude API): Set ANTHROPIC_API_KEY in /opt/agentx/secrets.env (VPS)
#   or run: docker compose -f "$SCAFFOLD/docker-compose.yml" run --rm ralph login
#
# VPS usage:
#   SCAFFOLD=/opt/agentx/scaffold ./ralph.sh
#   SCAFFOLD=/opt/agentx/scaffold ./ralph.sh plan 3
#
# Email listener (Python):
#   uv run --env-file /opt/agentx/secrets.env src/listener.py

SCAFFOLD="${SCAFFOLD:-$HOME/repos/claude/claudecode/scaffold}"

if [ ! -d "$SCAFFOLD" ]; then
    echo "Error: scaffold not found at $SCAFFOLD"
    echo "Set SCAFFOLD=/path/to/scaffold"
    exit 1
fi

export WORKSPACE_PATH="$(pwd)"
export RALPH_MAX_ITERATIONS="${RALPH_MAX_ITERATIONS:-5}"

if [ "$1" = "plan" ]; then
    export RALPH_MODE=plan
    [ -n "$2" ] && export RALPH_MAX_ITERATIONS="$2"
elif [[ "$1" =~ ^[0-9]+$ ]]; then
    export RALPH_MODE=build
    export RALPH_MAX_ITERATIONS="$1"
else
    export RALPH_MODE=build
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCAFFOLD" && exec docker compose -f "$SCRIPT_DIR/vps-compose.yml" up ralph
