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

### Step 1 — From your Mac: copy the GitHub deploy key to the VPS

The agent uses `~/.ssh/hostinger` to authenticate to GitHub as `runggp`. Copy it before the main session:

```bash
scp ~/.ssh/hostinger root@<vps-ip>:~/.ssh/hostinger
scp ~/.ssh/hostinger.pub root@<vps-ip>:~/.ssh/hostinger.pub
ssh root@<vps-ip> "chmod 600 ~/.ssh/hostinger"
```

> **One-time manual step:** Ensure `~/.ssh/hostinger.pub` is added to github.com/runggp → Settings → SSH Keys with **write access**.

> **Passphrase:** The `~/.ssh/hostinger` key on your Mac has a passphrase (use `ssh-add ~/.ssh/hostinger` to cache it locally). The copy on the VPS must be **passphraseless** — the agent runs unattended and cannot prompt for input. If the copied key still has a passphrase, strip it on the VPS:
> ```bash
> ssh-keygen -p -f ~/.ssh/hostinger  # enter current passphrase, leave new passphrase blank
> ```

---

### Step 2 — On the VPS

```bash
ssh root@<vps-ip>

# System
apt update && apt upgrade -y
# Use docker.io (Ubuntu pkg) — do NOT install containerd.io, it conflicts
apt install -y docker.io docker-compose-plugin git curl

# Git identity for the agent account
git config --global user.name "runggp"
git config --global user.email "agentx@runggp.com"

# Route GitHub through the deploy key
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/hostinger
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config

# Repos — clone before cd so the target directory is empty
git clone git@github.com:runggp/agentx.git /opt/agentx
git clone git@github.com:runggp/scaffold.git /opt/agentx/scaffold
cd /opt/agentx

# Secrets — copy from example, then fill in values
cp secrets.env.example secrets.env
nano secrets.env
chmod 600 secrets.env
# Also append git identity for the container (not in example, stays on VPS only):
cat >> secrets.env <<'EOF'

# Git identity for ralph container
GIT_CONFIG_COUNT=3
GIT_CONFIG_KEY_0=safe.directory
GIT_CONFIG_VALUE_0=*
GIT_CONFIG_KEY_1=user.name
GIT_CONFIG_VALUE_1=<git-username>
GIT_CONFIG_KEY_2=user.email
GIT_CONFIG_VALUE_2=<git-email>
EOF

# Agent SSH directory — ralph container runs as non-root; needs its own copy of
# the deploy key with matching ownership (uid 1000 = default useradd uid in container)
mkdir -p /opt/agentx/.agent-ssh
cp /root/.ssh/hostinger /opt/agentx/.agent-ssh/
chmod 700 /opt/agentx/.agent-ssh
chmod 600 /opt/agentx/.agent-ssh/hostinger
chown -R 1000:1000 /opt/agentx/.agent-ssh
cat > /opt/agentx/.agent-ssh/config <<'EOF'
Host github.com
  IdentityFile /home/ralph/.ssh/hostinger
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
EOF
chmod 600 /opt/agentx/.agent-ssh/config
chown 1000:1000 /opt/agentx/.agent-ssh/config

# Claude CLI
apt install -y nodejs npm
npm install -g @anthropic-ai/claude-code
claude login

# Smoke test (always run from main to avoid stale branch errors)
git checkout main
SCAFFOLD=/opt/agentx/scaffold ./ralph.sh plan 1
```

---

## Verification

```bash
docker ps          # Docker daemon running
claude --version   # Claude CLI installed and on PATH
# SCAFFOLD=/opt/agentx/scaffold ./ralph.sh plan 1 should start the loop, read IMPLEMENTATION_PLAN.md, exit after 1 iteration
```
