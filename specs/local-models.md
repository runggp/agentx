# Local Models — Ollama + LiteLLM

## Goal

Replace the Claude API backend with locally-hosted Qwen3 via Ollama, proxied through
LiteLLM so the scaffold's existing Anthropic SDK calls require no code changes — only
env var swaps.

## Architecture

```
ralph container
  └── Anthropic SDK  ──►  LiteLLM proxy (host:4000, Anthropic-compat API)
                               └──► Ollama (host:11434)
                                       └──► qwen3:8b (or qwen3:14b)
```

`network_mode: host` on the ralph container means it can reach both LiteLLM and Ollama
on localhost. No additional networking required.

## Prerequisites (manual, on VPS host)

1. **Install Ollama**
   ```bash
   curl -fsSL https://ollama.com/install.sh | sh
   systemctl enable --now ollama
   ```

2. **Pull the model**
   ```bash
   ollama pull qwen3:8b          # ~5 GB, fits in 16 GB RAM
   # ollama pull qwen3:14b       # ~9 GB — try if 8b quality is insufficient
   ```

3. **Verify**
   ```bash
   ollama list
   curl http://localhost:11434/api/tags
   ```

## LiteLLM Proxy

LiteLLM provides an Anthropic-compatible REST API on port 4000 that the scaffold's
Anthropic SDK will hit transparently when `ANTHROPIC_BASE_URL` is overridden.

### `litellm-config.yaml` (create at `/opt/agentx/litellm-config.yaml`)

```yaml
model_list:
  - model_name: ollama/qwen3:8b
    litellm_params:
      model: ollama/qwen3:8b
      api_base: http://127.0.0.1:11434
      timeout: 3600

  - model_name: ollama/qwen3:14b
    litellm_params:
      model: ollama/qwen3:14b
      api_base: http://127.0.0.1:11434
      timeout: 3600

  - model_name: claude-sonnet-4-6
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  request_timeout: 600
  drop_params: true
```

Notes:
- `model_name` must match `RALPH_MODEL` exactly (including the `ollama/` prefix)
- Use `127.0.0.1` not `localhost` to avoid IPv6 fallback overhead
- `drop_params: true` prevents unknown Anthropic params from erroring on Ollama
- `request_timeout: 600` forces connections to close after 10 min, preventing an aiohttp
  connection-reuse bug that causes 500 errors after ~48 min of accumulated requests
- Do not set `master_key` — if `LITELLM_MASTER_KEY` env var is present LiteLLM enforces
  auth on `/health`, which breaks the scaffold's health check poller

### `vps-compose.yml` changes

Uncomment the `litellm` service block and fill in:
```yaml
litellm:
  image: ghcr.io/berriai/litellm:main-latest
  env_file: ${WORKSPACE_PATH:-/opt/agentx}/secrets.env
  volumes:
    - ${WORKSPACE_PATH:-/opt/agentx}/litellm-config.yaml:/app/config.yaml:ro
  command: ["--config", "/app/config.yaml", "--port", "4000"]
  network_mode: host
  restart: unless-stopped
```

## Environment variables

Add to `secrets.env` on VPS:

```bash
ANTHROPIC_BASE_URL=http://localhost:4000   # redirect SDK to LiteLLM
ANTHROPIC_API_KEY=sk-...                   # still needed if Claude passthrough is configured
```

Switch model in `vps-compose.yml` ralph service:
```bash
RALPH_MODEL: qwen3:8b    # was: claude-sonnet-4-6
```

To revert to Claude API: remove `ANTHROPIC_BASE_URL` and restore `RALPH_MODEL`.

## Benchmarking

After wiring, run a representative task and compare:
- Wall-clock time per loop iteration
- Token throughput (tokens/sec from Ollama logs)
- Task completion quality (does the output match Claude's?)
- Cost: $0 local vs. Claude API spend from session logs

Ollama metrics endpoint: `http://localhost:11434/api/ps`

## Acceptance Criteria

- [ ] `ollama list` shows `qwen3:8b` on VPS host
- [ ] LiteLLM proxy container starts and responds to `curl http://localhost:4000/health`
- [ ] `ralph.sh` completes at least one full iteration with `RALPH_MODEL=qwen3:8b` and `ANTHROPIC_BASE_URL=http://localhost:4000`
- [ ] Session log shows model `qwen3:8b` (not `claude-sonnet-4-6`)
- [ ] At least one commit produced by the local-model run
