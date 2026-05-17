# AGENTS.md

## Project Goal

A VPS-hosted autonomous agent that receives task specs via email (agentx@runggp.com), runs Claude-powered Ralph loops, and replies with results — bootstrapped with Claude API, evolving toward local Qwen3 models.

## Tech Stack

- **Python 3.14** — IMAP email listener, spec parser, SMTP responder
- **Bash** — Ralph loop (adapted from scaffold: https://github.com/runggp/scaffold)
- **Docker / Docker Compose** — containerized execution on Ubuntu 24.04 VPS
- **Claude API** — model backend (Phase 1); Ollama/Qwen3 added in Phase 2
- **Hostinger KVM 4** — 4 vCPU, 16 GB RAM, 200 GB NVMe

## Build & Run

```bash
# Local dev
docker compose up

# On VPS
./ralph.sh        # build mode
./ralph.sh plan   # plan mode
```

## Validation

- Tests: `uv run --dev pytest --tb=short -v`
- Lint: `uv run --dev ruff check src/`
- Types: `uv run --dev mypy src/listener.py`

## Self-Monitoring

At the start of each session, read the session log to understand past work and spend:

```bash
uv run summarize_sessions.py --last 10
```

Or read `logs/sessions.jsonl` directly. Each line is a JSON record with:
- `session_id`, `started_at`, `completed_at`, `duration_seconds`
- `task_description`, `spec_preview`, `sender`
- `exit_code`, `timed_out`, `output_tail`
- `cost_usd` (session cost), `cumulative_cost_usd` (running total)

Use this to: check recent task outcomes, estimate remaining budget, avoid re-doing completed work.

## Spend Controls (env vars)

| Var | Default | Effect |
|---|---|---|
| `AGENTX_SPEND_CEILING_USD` | 0 (off) | Stop loop when cumulative spend hits this |
| `AGENTX_SPEND_ALERT_USD` | 0 (off) | Email alert when cumulative spend hits this |
| `AGENTX_SPEND_ALERT_EMAIL` | "" | Email address for spend alerts |

## Sending Self-Tasks

```bash
uv run --env-file /opt/agentx/secrets.env send_self_task.py
uv run --env-file /opt/agentx/secrets.env send_self_task.py --subject "[task] custom" --spec specs/my-spec.md
```

## Operational Notes

- `src/` files may be root-owned in the Docker container environment (from prior git operations). Use git plumbing (`git hash-object -w`, `git update-index --cacheinfo`, `git commit-tree`) to commit changes without filesystem write access.
- The email listener runs on the VPS host (not in Docker): `uv run --env-file /opt/agentx/secrets.env src/listener.py`
- Session logs written to `logs/sessions/` (individual JSON) and `logs/sessions.jsonl` (append-only)
