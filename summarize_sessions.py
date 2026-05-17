#!/usr/bin/env python3
"""
Summarize agentx session logs for agent self-monitoring.

Reads logs/sessions.jsonl and prints a concise summary of past sessions,
cumulative spend, and recent task history.

Usage (agent reads this output as a tool input at session start):
    uv run summarize_sessions.py
    uv run summarize_sessions.py --json          # machine-readable output
    uv run summarize_sessions.py --last 5        # last N sessions only

This script is designed to be called by the agent at the start of each
ralph loop iteration so it can make cost-aware decisions.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def load_sessions(jsonl_path: Path) -> list[dict]:  # type: ignore[type-arg]
    sessions = []
    if not jsonl_path.exists():
        return sessions
    with jsonl_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                sessions.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return sessions


def fmt_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    return f"{seconds / 60:.1f}m"


def fmt_cost(cost: float) -> str:
    return f"${cost:.6f}"


def print_summary(sessions: list[dict], last: int | None = None) -> None:  # type: ignore[type-arg]
    if not sessions:
        print("No sessions recorded yet.")
        return

    if last is not None:
        sessions = sessions[-last:]

    total_cost = sum(float(s.get("cost_usd", 0.0)) for s in sessions)
    total_duration = sum(float(s.get("duration_seconds", 0.0)) for s in sessions)
    success_count = sum(1 for s in sessions if s.get("exit_code") == 0 and not s.get("timed_out"))
    fail_count = sum(1 for s in sessions if s.get("exit_code") != 0)
    timeout_count = sum(1 for s in sessions if s.get("timed_out"))

    cumulative = float(sessions[-1].get("cumulative_cost_usd", total_cost)) if sessions else 0.0

    print("=== agentx session summary ===")
    print(f"Sessions shown: {len(sessions)}")
    print(f"Cumulative cost (all time): {fmt_cost(cumulative)}")
    print(f"Cost this view: {fmt_cost(total_cost)}")
    print(f"Total duration: {fmt_duration(total_duration)}")
    print(f"Outcomes: {success_count} ok / {fail_count} failed / {timeout_count} timed out")
    print()
    print(f"{'Started':<20} {'Duration':>8} {'Cost':>12} {'Exit':>5}  Task")
    print("-" * 80)

    for s in sessions:
        started = str(s.get("started_at", ""))[:19].replace("T", " ")
        duration = fmt_duration(float(s.get("duration_seconds", 0)))
        cost = fmt_cost(float(s.get("cost_usd", 0)))
        exit_code = s.get("exit_code")
        timed_out = s.get("timed_out", False)
        status = "TO" if timed_out else str(exit_code) if exit_code is not None else "?"
        task = s.get("task_description", "")[:50]
        print(f"{started:<20} {duration:>8} {cost:>12} {status:>5}  {task}")


def print_json(sessions: list[dict], last: int | None = None) -> None:  # type: ignore[type-arg]
    if last is not None:
        sessions = sessions[-last:]
    cumulative = float(sessions[-1].get("cumulative_cost_usd", 0)) if sessions else 0.0
    total_cost = sum(float(s.get("cost_usd", 0.0)) for s in sessions)
    output = {
        "session_count": len(sessions),
        "cumulative_cost_usd": cumulative,
        "view_cost_usd": total_cost,
        "sessions": sessions,
    }
    print(json.dumps(output, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize agentx session logs")
    parser.add_argument("--json", action="store_true", help="Output JSON instead of human-readable")
    parser.add_argument("--last", type=int, default=None, help="Show only the last N sessions")
    parser.add_argument("--workspace", default=None, help="Path to workspace (default: cwd)")
    args = parser.parse_args()

    workspace = Path(args.workspace) if args.workspace else Path.cwd()
    jsonl_path = workspace / "logs" / "sessions.jsonl"

    sessions = load_sessions(jsonl_path)

    if args.json:
        print_json(sessions, last=args.last)
    else:
        print_summary(sessions, last=args.last)


if __name__ == "__main__":
    main()
