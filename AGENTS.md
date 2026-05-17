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

- Tests: `pytest src/tests/`
- Lint: `ruff check src/`
- Types: `mypy src/`
- Session logs: `logs/sessions/<session-id>.json` after each iteration

## Operational Notes

_Ralph will update this section as it learns about the codebase._

### Codebase Patterns

_Document patterns as they emerge._
