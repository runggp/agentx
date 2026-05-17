# Implementation Plan

## Current Focus

- [ ] **Phase 1: Spend tracking** — Log token estimates per iteration, session ceiling, email alert on threshold
- [ ] **Phase 2: Local models** — Install Ollama, pull Qwen3-14B, wire LiteLLM, benchmark vs Claude API
- [ ] **Phase 2.1: Model router** — Route tasks to models based on type; local for cost, API for quality
- [ ] **Phase 3: Self-monitoring** — Agent reads its own cost log and audit trail as tool inputs

## Completed

- [x] **Phase 0a: VPS baseline** — SSH, Docker, git, credentials — see `specs/vps-setup.md`
- [x] **Phase 0b: Lift and shift** — scaffold runs on VPS with Claude API (OAuth mode)
- [x] **Phase 0c: VPS compose** — `vps-compose.yml` with VPS paths, persistent workspace, Entire enabled
- [x] **Phase 0d: Structured logging** — `write_session_log` in `src/listener.py` writes `logs/sessions/<uuid>.json` per ralph.sh invocation and appends to `logs/sessions.jsonl`. Schema: session_id, started_at, completed_at, duration_seconds, task_description, spec_preview, sender, exit_code, timed_out, output_tail. Future agent iterations read `sessions.jsonl` to understand past work.
- [x] **Phase 0e: Email listener** — `src/listener.py` implements async IMAP polling (aioimaplib), spec extraction from body/.md attachment, Ralph dispatch via subprocess, SMTP reply (aiosmtplib), and `[stop]`/`[status]` control commands. Tests in `src/tests/test_listener.py`. Run on VPS host: `uv run --env-file /opt/agentx/secrets.env src/listener.py`
- [x] **Phase 0f: First self-task** — `send_self_task.py` at workspace root sends a `[task]` email to agentx@runggp.com. Default spec is "deploy this harness to VPS". Run: `uv run --env-file /opt/agentx/secrets.env send_self_task.py`. Accepts `--subject` and `--spec` flags to customise.

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
- In the build agent environment, `src/` files may be owned by root (from prior Docker-run git checkout). Use git plumbing (`git hash-object -w`, `git update-index --cacheinfo`) to stage changes without needing filesystem write access to root-owned files.
