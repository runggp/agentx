# Implementation Plan

## Current Focus

Email listener system (`specs/email-listener.md`) — the primary remaining work.

`pyproject.toml` is fully configured (`aioimaplib`, `aiosmtplib`, `mistletoe` deps; pytest, ruff, mypy dev deps). No `src/` Python files exist yet.

---

## Remaining Tasks

### 1. Core Email Listener Module — `src/listener.py`
- [ ] IMAP IDLE connection with `aioimaplib`
- [ ] Polling fallback (60s interval) if IDLE not supported
- [ ] Exponential backoff reconnection (1s→2s→4s→8s, max 60s)
- [ ] IDLE timeout refresh at 29 min (before server 30min cutoff)
- [ ] `process_new_messages()` — search UNSEEN, dispatch, mark read
- [ ] JSON structured logging (`JsonFormatter` as specified)
- [ ] 5-minute heartbeat log when idle
- [ ] HTTP health endpoint for external monitoring
- [ ] Systemd-ready entry point (`uv run --env-file ... src/listener.py`)

### 2. Email Parser — `src/parser.py`
- [ ] Subject pattern matching: `^\[task\]\s+(.+)$`
- [ ] Authorized sender check via `AGENTX_ALLOWED_SENDERS` env var
- [ ] Spec extraction priority: `.md` attachment → markdown code block → plain text body
- [ ] HTML stripping from email bodies
- [ ] Attachment size limit (1MB)
- [ ] `validate_task_spec()` — min 50 chars, max 10KB, warn if no goal section
- [ ] Basic prompt injection scan / audit logging

### 3. Workspace Isolation — `src/workspace.py`
- [ ] `create_workspace()` — git clone `/home/ralph/workspace` to `/tmp/agentx-workspaces/task-{id}`
- [ ] Fresh branch creation: `ralph/task-{id}-{timestamp}`
- [ ] Write `TASK_SPEC.md` into workspace
- [ ] Cleanup policy: success → delete after reply sent; failure → keep 6h; stale (>24h) → auto-delete

### 4. Ralph Loop Runner — `src/runner.py`
- [ ] `run_ralph_loop()` — invoke `ralph.sh` via `asyncio.subprocess`
- [ ] Pass `WORKSPACE_PATH`, `RALPH_MAX_ITERATIONS=10`, `RALPH_MODE=build` env vars
- [ ] 30-minute timeout (`communicate(timeout=1800)`)
- [ ] Capture stdout/stderr, git commits, diff summary, duration

### 5. SMTP Responder — `src/responder.py`
- [ ] `send_reply()` — `aiosmtplib` with SSL/TLS on port 465
- [ ] 3-attempt retry with exponential backoff
- [ ] `format_reply()` — status, duration, branch, commit count, spec excerpt, last 1KB output
- [ ] Proper `email.message.EmailMessage` construction (In-Reply-To, References headers)

### 6. Rate Limiting
- [ ] Max 5 tasks/hour per sender
- [ ] Max 20 tasks/day total
- [ ] Temporary sender blacklist for abuse

### 7. Tests
- [ ] `src/tests/test_parser.py` — subject matching, sender auth, spec extraction, validation
- [ ] `src/tests/test_workspace.py` — creation, cleanup policies
- [ ] `src/tests/test_responder.py` — reply formatting, SMTP retry logic
- [ ] `src/tests/test_runner.py` — subprocess execution, timeout handling
- [ ] `src/tests/test_listener.py` — IDLE/polling logic, reconnection backoff

### 8. Deployment
- [ ] Systemd unit file for `agentx-listener.service` (as per spec)
- [ ] Add `AGENTX_ALLOWED_SENDERS` and `AGENTX_LOG_FILE` to `secrets.env.example`
- [ ] Document listener startup in `specs/vps-setup.md` or README

---

## Completed

### VPS + Scaffold Infrastructure ✓
- Docker scaffold (`scaffold/`) fully implemented with Dockerfile, entrypoint, loop, output formatter
- `vps-compose.yml` configured for VPS deployment with volume mounts and env vars
- `secrets.env.example` with IMAP/SMTP placeholders
- `specs/vps-setup.md` — complete setup guide
- `pyproject.toml` — Python deps configured for email listener project
- `.agent-claude/` and `.agent-ssh/` directories set up on VPS

### Scaffold Improvements ✓ (from previous plan)
- README.md restructured (418→119 lines), Ollama/advanced docs extracted
- Work summary functionality in `loop.sh`
- Node.js output formatter integrated
- Environment variable input validation
- Test suite fixes
