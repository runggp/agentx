# VPS Agent Harness Spec

## Direction

**Custom harness. No NemoClaw.**

Build on the existing Ralph Wiggum loop (`/repos/claude/claudecode/ralph-docker`) — refactoring it from a Docker-on-local-machine setup to a VPS-native container harness. Start with Claude API as the model backend, add local models (Ollama/Qwen3) as a second layer once the loop is stable.

Build it agentically. Document the work on the blog as it progresses.

---

## What Ralph Already Gives Us

The `ralph-docker` repo is a solid foundation. Key things to keep:

- **The loop pattern** — each iteration: read disk state → call model → tool dispatch → commit → repeat
- **Fresh context per iteration** — Claude reads `IMPLEMENTATION_PLAN.md` and `specs/*` fresh each run; makes the loop resumable
- **Git branch isolation** — `ralph/{name}-{timestamp}` branches, never touches main
- **Error detection** — spending cap, rate limits, auth failures all stop the loop cleanly
- **Iteration limits** — `RALPH_MAX_ITERATIONS` prevents runaway loops
- **Non-root container execution** — `ralph` user, workspace-bounded mounts
- **LiteLLM proxy** — already wired for local model support (Ollama)
- **Prompt hierarchy** — project-level prompts override defaults; local-model variants supported

What changes: the execution environment moves from Docker on a dev machine to a container on the Hostinger VPS. The agent lives there permanently, not just during a dev session.

---

## VPS Setup

**Hardware:** Hostinger KVM 4 — 4 vCPU, 16 GB RAM, 200 GB NVMe  
**OS:** Ubuntu 24.04  
**Model backend (Phase 1):** Claude API (Anthropic) — `claude-sonnet-4-6` or `claude-opus-4-7`  
**Model backend (Phase 2):** Ollama local models on same VPS  

### Model Progression

| Phase | Backend | Model | RAM use | Notes |
|---|---|---|---|---|
| 1 | Claude API | Sonnet 4.6 / Opus 4.7 | minimal | Start here — proven, reliable |
| 2 | Ollama | Qwen3-14B Q4_K_M | ~9 GB | Local fallback / cost control |
| 2+ | Ollama | Qwen3-32B Q3_K_M | ~13 GB | Higher-capability local option |
| ongoing | Router | task-dependent | varies | Route by task type (see below) |

**Note on Qwen3-35B Q3:** needs ~14–15 GB, leaving <2 GB after OS overhead. Risky. Benchmark actual memory under load before committing.

---

## Docker → VPS Refactor

The core change: instead of `docker compose up` from a dev machine mounting a local workspace, the container runs persistently on the VPS.

### Key Differences

| Concern | Docker (current) | VPS target |
|---|---|---|
| Execution host | Local machine | Hostinger KVM 4 |
| Container runtime | Docker Desktop / Compose | Docker on Ubuntu (or Podman) |
| Workspace path | Host `WORKSPACE_PATH` mount | VPS-local directory |
| Ollama | Via `host.docker.internal` → local machine | localhost on same VPS |
| SSH keys | Mounted from `~/.ssh` on dev machine | VPS `~/.ssh` |
| Claude credentials | Mounted from `~/.claude` on dev machine | VPS `~/.claude` |
| Trigger mechanism | Manual `./ralph.sh` | Cron, webhook, or manual SSH |
| Observability | Terminal stdout | Structured logs + optional dashboard |

### What to Preserve From ralph-docker

- `scripts/loop.sh` — the iteration engine (minimal changes needed)
- `scripts/entrypoint.sh` — auth detection and validation
- `scripts/setup-workspace.sh` — project scaffolding
- `Dockerfile` — base image (node:22-slim + claude CLI)
- `docker-compose.yml` — adapt for VPS paths and Ollama localhost
- `litellm-config.yaml` + `litellm.Dockerfile` — ready for Phase 2
- All prompt files (`prompts/`, `skills/ralph.md`)

### What to Add / Change

- `vps-compose.yml` — VPS-specific compose override (paths, networking, Ollama localhost)
- Structured log output (JSON to file, not just stdout)
- Persistent workspace on VPS NVMe (not a transient mount)
- Cron or trigger mechanism for scheduled agent runs
- Budget/cost tracking hook (precursor to self-managing agent)

---

## Multi-Model Router

Design `model_router(task_type) -> model_id` as a first-class concern from the start.

```
task types → model
─────────────────────────────────────────────
planning, architecture   → claude-opus-4-7 (API)
general build, iteration → claude-sonnet-4-6 (API) or Qwen3-14B (local)
fast/cheap tasks         → Qwen3-1.7B or Phi-3-mini (local, Phase 2)
code generation          → Qwen2.5-Coder (local, Phase 2)
tasks exceeding local    → Claude API fallback
```

In `loop.sh`: read task type from `IMPLEMENTATION_PLAN.md` metadata or a `RALPH_MODEL` env var. Phase 1: env var only. Phase 2: automatic routing.

---

## Safety, Security & Control Pillars

These are non-negotiable properties, iterated continuously. User retains ultimate control at all times.

### 1. Iteration control
- `RALPH_MAX_ITERATIONS` hard cap always set
- Loop stops on any auth/spend/rate-limit signal
- Manual kill via SSH always works (no auto-restart policy)

### 2. Blast radius containment
- Agent operates within a bounded workspace directory
- No access to host filesystem outside that boundary
- Non-root container user (`ralph`)
- Read-only mounts for credentials and SSH keys

### 3. Prompt injection defense
- Tool outputs (web fetch, file reads from external sources) are treated as untrusted
- System prompt vs. tool result separation in context
- Flag model outputs that attempt to override instructions

### 4. Audit trail
- Every iteration logged: timestamp, model used, task attempted, tools called, files changed, commit hash
- Git branch per run — full diff always reviewable before merge
- Human reviews and merges PRs; agent never touches main

### 5. Spend visibility
- Log API calls with estimated token counts per iteration
- Alert threshold: configurable spend-per-session ceiling
- Phase 2: agent reads its own cost log as a tool input (self-monitoring)

### 6. Graceful degradation
- Auth failure → stop, don't retry
- Model unavailable → log and stop, don't fall through silently
- Network error → retry with backoff, then stop

---

## Email Trigger

**Trigger mechanism: email to `agentx@rubggp.com`**

The agent is awakened by email. A spec file (markdown attachment or inline body) sent to `agentx@rubggp.com` defines the next task. The agent reads it, runs the Ralph loop, and replies with a status summary when done.

### Email → Task Flow

```
User sends email to agentx@rubggp.com
  └─ Attachment or body: spec/task markdown
       └─ Mail listener on VPS detects new message
            └─ Extracts spec, writes to workspace/TASK.md
                 └─ Triggers Ralph loop
                      └─ Agent works, commits to branch
                           └─ Reply email: summary, branch name, diff link
```

### VPS Mail Stack

The Hostinger domain (`rubggp.com`) already has email. On the VPS:

- **Receiving:** Hostinger mail server handles delivery (IMAP-accessible, confirmed)
- **Listener:** Python script polls Hostinger IMAP for new mail to `agentx@rubggp.com`
- **Parser:** Extracts markdown spec from body or first `.md` attachment
- **Dispatcher:** Writes spec to workspace, fires `ralph.sh`
- **Responder:** On loop completion, sends reply via SMTP with work summary

### Spec Email Format (convention)

```
Subject: [task] <short description>
Body or attachment: markdown spec file

The spec should include:
  - Goal
  - Acceptance criteria
  - Constraints / out of scope
  - Any relevant context or links
```

Subject prefix `[task]` distinguishes task emails from noise. Other prefixes reserved for future use (`[status]`, `[stop]`, `[config]`).

### Control via Email

Even before the full harness is self-managing, email gives a simple control surface:

| Email subject | Action |
|---|---|
| `[task] <description>` | Start a new task loop |
| `[stop]` | Gracefully halt current loop after iteration |
| `[status]` | Reply with current loop state and recent commits |

---

## Build Process

### Bootstrapping Paradox

The agent doesn't exist yet — so it can't build itself from scratch. **Phase 0 is done by Claude Code** (this session) working directly. Once the harness is live on the VPS and email-triggered, subsequent iterations are driven agentically: send a spec email, agent builds the next feature, human reviews and merges.

```
Phase 0: Claude Code (this session) builds and deploys the harness
Phase 1+: Agent receives spec emails and builds its own improvements
```

**Blog as you go.** Use `/blog` after each meaningful iteration to publish. Eventually the agent may manage its own social media presence — for now it's a human-in-the-loop step.

---

## Implementation Plan (Initial)

- [ ] **Phase 0a: VPS baseline** — SSH in, install Docker, verify connectivity, pull ralph-docker
- [ ] **Phase 0b: Lift and shift** — Run ralph-docker on VPS with Claude API, confirm loop works end-to-end
- [ ] **Phase 0c: VPS compose** — `vps-compose.yml` with VPS-specific paths, persistent workspace on NVMe
- [ ] **Phase 0d: Structured logging** — JSON log per session, readable by future agent iterations
- [ ] **Phase 0e: Email listener** — IMAP poller + spec extractor + Ralph dispatcher + reply sender
- [ ] **Phase 0f: First self-task** — Send spec email to agentx@rubggp.com: "deploy this harness to VPS"
- [ ] **Phase 1: Spend tracking** — Log token estimates per iteration, session ceiling, email alert on threshold
- [ ] **Phase 2: Local models** — Install Ollama, pull Qwen3-14B, wire LiteLLM, benchmark vs Claude API
- [ ] **Phase 2.1: Model router** — Route tasks to models based on type; local for cost, API for quality
- [ ] **Phase 3: Self-monitoring** — Agent reads its own cost log and audit trail as tool inputs
- [ ] **Ongoing: Safety iteration** — Each cycle tightens one safety/security/reliability property

---

## Open Questions

- Blog platform: existing setup or new? (affects blog-as-artifact workflow)
- SSH access pattern to VPS: direct key auth assumed — confirm
- SSH access pattern to VPS: direct key auth assumed — confirm
