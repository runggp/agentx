# Implementation Plan

## Status Legend
- `[ ]` — not started
- `[~]` — implemented, pending real-world verification (mocked tests pass, live behavior unconfirmed)
- `[x]` — verified complete (real execution observed or behavior is fully deterministic)

## Current Focus

- [~] **Phase 0f: First self-task** — `src/send_task.py` runs on VPS host and sends email successfully (confirmed). Pending: listener picks up incoming `[task]` email, dispatches a ralph loop, and sends a reply. Note: send_task.py must run on the VPS host — email credentials are not available inside the Docker container.
- [ ] **Phase 2: Local models** — Install Ollama on VPS host, pull a model (see `specs/local-models.md` once written), wire LiteLLM proxy, benchmark vs Claude API. Requires manual Ollama install before ralph can proceed.
- [ ] **Phase 2.1: Model router** — Route tasks to models based on type; local for cost, API for quality

## Completed

- [x] **Phase 0a: VPS baseline** — SSH, Docker, git, credentials — see `specs/vps-setup.md`
- [x] **Phase 0b: Lift and shift** — scaffold runs on VPS with Claude API (OAuth mode)
- [x] **Phase 0c: VPS compose** — `vps-compose.yml` with VPS paths, persistent workspace, Entire enabled
- [x] **Phase 0d: Structured logging** — `scaffold/lib/session-logger.js` parses Claude stream-json after each iteration, writes `logs/sessions/<session-id>.json` with timestamp, model, cost, tokens, tools_called, files_changed, commit_hash. Called from `scaffold/scripts/loop.sh` — non-blocking, degrades gracefully. Tests in `scaffold/tests/test_session_logger.js`.
- [x] **Phase 0e: Email listener** — `src/listener.py` implements async IMAP polling (aioimaplib), spec extraction from body/.md attachment, Ralph dispatch via subprocess, SMTP reply (aiosmtplib), and `[stop]`/`[status]` control commands. Tests in `src/tests/test_listener.py`. Run on VPS host: `uv run --env-file /opt/agentx/secrets.env src/listener.py`
- [x] **Phase 1: Spend tracking** — `check-spend` command in `scaffold/lib/session-logger.js` reads session JSON, sums iteration costs, exits 2 if `RALPH_SPEND_CEILING_USD` exceeded. `loop.sh` checks spend after every iteration and stops with a notification email. Ceiling defaults to 0 (disabled). 18 tests pass. `secrets.env.example` documents the new var.
- [x] **Phase 3: Self-monitoring** — `scaffold/lib/session-logger.js` `report` command reads all `logs/sessions/*.json` and outputs a markdown audit trail. `scaffold/scripts/loop.sh` prepends this report to the prompt before each loop. Verified: the "## Prior Session Audit Trail" section appeared in an actual loop run prompt.

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
- `uv` is installed in the Docker container — ralph can run `uv run` for Python scripts and `uv run --dev pytest` for tests
- The listener (`src/listener.py`) runs on the VPS host as a long-running daemon, not inside Docker
- `pyproject.toml` specifies Python >=3.14; uv installs the correct version automatically
- Listener secrets come from `secrets.env` via `--env-file` flag; never baked into Docker
- `SMTP_USER` is always implicitly allowed by the listener — self-sent tasks work regardless of `AGENTX_ALLOWED_SENDERS`
