# Task: Research Local Models

Research the feasibility and setup requirements for running local models on the VPS.

## Goal

Write `specs/local-models.md` covering:
1. Ollama installation on Ubuntu 24.04 (steps, prerequisites)
2. Recommended Qwen3 model variants for the VPS (4 vCPU, 16GB RAM, 200GB NVMe):
   - Qwen3-14B Q4_K_M (~9GB RAM) as primary candidate
   - Qwen3-32B Q3_K_M (~13GB RAM) as stretch goal
3. LiteLLM proxy config snippet for `litellm-config.yaml` to route to Ollama
4. Benchmark plan: latency and quality vs Claude API for typical Ralph tasks
5. Manual operator steps required before ralph can proceed

## Constraints

- Operator must manually install Ollama on the VPS host (outside Docker)
- ralph can wire LiteLLM and run benchmarks once Ollama is running
- Do not modify `loop.sh` or model routing until `specs/local-models.md` is written

## Acceptance

`specs/local-models.md` exists and covers all five points above.
