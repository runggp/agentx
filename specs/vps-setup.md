# VPS Setup Guide

## Local Machine vs. Docker for Setup

Use your local Mac directly. Docker adds no meaningful security here — Docker isolation protects the host from the container, not the reverse. If the Mac is compromised, an attacker sees everything the container does anyway. Forwarding an SSH agent into a container reintroduces the same attack surface.

---

## What Actually Matters

**SSH key hygiene**
- Use ed25519 key with a passphrase (`~/.ssh/id_ed25519`)
- Never copy the private key to the VPS

**Credentials in shell history**
- Don't: `export ANTHROPIC_API_KEY=sk-...` in an interactive shell (goes into `~/.bash_history`)
- Do: write directly to `/opt/agentx/secrets.env` via `nano`/`vim`, or:
  ```bash
  cat > /opt/agentx/secrets.env   # paste values, then Ctrl+D
  chmod 600 /opt/agentx/secrets.env
  ```

**VPS hardening (one-time)**
- Disable password SSH auth: `PasswordAuthentication no` in `/etc/ssh/sshd_config`
- Enable firewall: `ufw allow OpenSSH && ufw enable`

---

## Phase 0a Setup Sequence

```bash
ssh root@<vps-ip>

# System
apt update && apt upgrade -y
apt install -y docker.io docker-compose-plugin git curl

# Workspace
mkdir -p /opt/agentx/workspace
cd /opt/agentx

# Repos
git clone git@github.com:arosenfeld2003/agentx.git .
git clone <ralph-docker-repo-url> ralph-docker

# Secrets (see secrets.env.example for required keys)
nano secrets.env
chmod 600 secrets.env

# Claude auth (one-time, interactive)
curl -fsSL https://claude.ai/install.sh | sh
claude login

# Smoke test
RALPH_DOCKER=/opt/agentx/ralph-docker ./ralph.sh plan 1
```

---

## Verification

```bash
docker ps          # Docker daemon running
claude --version   # Claude CLI installed and on PATH
# ralph.sh plan 1 should start the loop, read IMPLEMENTATION_PLAN.md, exit after 1 iteration
```
