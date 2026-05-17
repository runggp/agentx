# Implementation Plan

## Current Focus

- [ ] **Phase 0f: First self-task** — Send spec email to agentx@runggp.com: "deploy this harness to VPS"
- [ ] **Phase 2: Local models** — Install Ollama, pull Qwen3-14B, wire LiteLLM, benchmark vs Claude API
- [ ] **Phase 2.1: Model router** — Route tasks to models based on type; local for cost, API for quality
- [ ] **Phase 3: Self-monitoring** — Agent reads its own cost log and audit trail as tool inputs

## Completed

- [x] **Phase 0a: VPS baseline** — SSH, Docker, git, credentials — see `specs/vps-setup.md`
- [x] **Phase 0b: Lift and shift** — scaffold runs on VPS with Claude API (OAuth mode)
- [x] **Phase 0c: VPS compose** — `vps-compose.yml` with VPS paths, persistent workspace, Entire enabled
- [x] **Phase 0d: Structured logging** — Phase 0d complete: `scaffold/lib/session-logger.js` parses Claude stream-json after each iteration, writes `logs/sessions/<session-id>.json` with timestamp, model, cost, tokens, tools_called, files_changed, commit_hash. Called from `scaffold/scripts/loop.sh` — non-blocking, degrades gracefully. Tests in `scaffold/tests/test_session_logger.js` (12 tests).
- [x] **Phase 0e: Email listener** — `src/listener.py` implements async IMAP polling (aioimaplib), spec extraction from body/.md attachment, Ralph dispatch via subprocess, SMTP reply (aiosmtplib), and `[stop]`/`[status]` control commands. Tests in `src/tests/test_listener.py`. Run on VPS host: `uv run --env-file /opt/agentx/secrets.env src/listener.py`
- [x] **Phase 1: Spend tracking** — `check-spend` command added to `scaffold/lib/session-logger.js`. Reads session JSON, sums iteration costs, exits 2 if `RALPH_SPEND_CEILING_USD` is exceeded. `loop.sh` checks spend after every iteration and stops with a `send-notification.sh` email alert. Ceiling defaults to 0 (disabled). 18 tests pass (up from 12). `secrets.env.example` documents the new var.

## Notes

### Running tests (requires Python and uv on the VPS host)
```bash
cd /opt/agentx
uv run --dev pytest
uv run --dev pytest --tb=short -v
```

### Linting + type-check
```bash
uv run --dev ruff check src/
uv run --dev mypy src/listener.py
```

### Known constraints
- Docker container (node:22-slim) has no Python — listener runs on VPS host, not inside Docker
- `pyproject.toml` specifies Python >=3.14; uv installs the correct version automatically
- Listener secrets come from `secrets.env` via `--env-file` flag; never baked into Docker
