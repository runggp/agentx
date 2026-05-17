# Entire Observability

Entire captures AI session metadata — prompts, responses, tool calls, files touched, token usage — on a shadow git branch alongside code. This gives a deterministic audit trail of *why* Ralph made each decision, not just *what* it changed.

## How It Works

On startup, Ralph runs `entire enable --strategy manual-commit` in the workspace. From then on, each time Ralph commits code, Entire records a checkpoint on the shadow branch `entire/checkpoints/v1`. When Ralph pushes code, the checkpoint branch is pushed too.

**Strategy: `manual-commit`** — checkpoints are tied to git commits, so the decision record is co-located with the code changes it produced. This is the right fit for ralph sessions where each commit represents a meaningful unit of work.

## Viewing Session Records

```bash
# List all checkpoints
git log entire/checkpoints/v1 --oneline

# Inspect a specific checkpoint
git show entire/checkpoints/v1

# Fetch remote checkpoints (after a VPS run)
git fetch origin entire/checkpoints/v1
git log FETCH_HEAD --oneline
```

## Configuration (vps-compose.yml)

Entire is enabled by default on the VPS:

| Variable | Value | Meaning |
|---|---|---|
| `RALPH_ENTIRE_ENABLED` | `true` | On by default |
| `RALPH_ENTIRE_STRATEGY` | `manual-commit` | Checkpoint on each git commit |
| `RALPH_ENTIRE_PUSH_SESSIONS` | `true` | Push `entire/checkpoints/v1` to remote |
| `RALPH_ENTIRE_LOG_LEVEL` | `warn` | Quiet unless something goes wrong |

## Disabling for a Single Run

```bash
RALPH_ENTIRE_ENABLED=false ./ralph.sh build 2
```

## Startup Confirmation

When Entire initializes correctly, the ralph container logs:

```
[ralph] Entire enabled (manual-commit)
```

If the binary is missing or setup fails, ralph continues normally — Entire never blocks the loop.
