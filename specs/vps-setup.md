# VPS Setup Guide

## What Actually Matters

**SSH key hygiene**
- Use ed25519 key with a passphrase (`~/.ssh/id_ed25519`) for your own VPS access
- The GitHub deploy key (`~/.ssh/hostinger`) must be **passphraseless** on the VPS — the agent runs unattended

**Credentials in shell history**
- Don't: `export ANTHROPIC_API_KEY=sk-...` in an interactive shell (goes into `~/.bash_history`)
- Do: write directly to `/opt/agentx/secrets.env` via `nano`/`vim`

**VPS hardening (one-time)**
- Disable password SSH auth: `PasswordAuthentication no` in `/etc/ssh/sshd_config`
- Enable firewall: `ufw allow OpenSSH && ufw enable`

---

## Phase 0a Setup Sequence

### Step 1 — From your Mac: copy the GitHub deploy key to the VPS

```bash
scp ~/.ssh/hostinger root@<vps-ip>:~/.ssh/hostinger
scp ~/.ssh/hostinger.pub root@<vps-ip>:~/.ssh/hostinger.pub
ssh root@<vps-ip> "chmod 600 ~/.ssh/hostinger"
```

> **One-time manual step:** Add `~/.ssh/hostinger.pub` to github.com/runggp → Settings → SSH Keys with **write access**.

> **Passphrase:** Strip the passphrase from the VPS copy — the agent cannot prompt for input:
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
apt install -y docker.io docker-compose-plugin git curl nodejs npm

# Git identity for the agent account
git config --global user.name "<git-username>"
git config --global user.email "<git-email>"

# Route GitHub through the deploy key (for root on VPS host)
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/hostinger
  StrictHostKeyChecking accept-new
EOF
chmod 600 ~/.ssh/config

# Clone repos — clone before creating any subdirs so target dirs are empty
git clone git@github.com:runggp/agentx.git /opt/agentx
git clone git@github.com:runggp/scaffold.git /opt/agentx/scaffold

# Give ralph (uid 1001 in container) ownership of the workspace so it can
# write to .git when creating branches
chown -R 1001:1001 /opt/agentx
# Allow root to still run git on this repo despite the ownership mismatch
git config --global --add safe.directory /opt/agentx

cd /opt/agentx

# Secrets — fill in IMAP/SMTP values; leave ANTHROPIC_API_KEY blank (OAuth used instead)
cp secrets.env.example secrets.env
nano secrets.env
chmod 600 secrets.env

# Append git identity for the ralph container (stays on VPS only, not in git).
# GIT_AUTHOR/COMMITTER env vars are used instead of GIT_CONFIG_COUNT which
# does not reliably propagate through docker env_file loading.
cat >> secrets.env <<'EOF'

# Git identity for commits made inside the container
GIT_AUTHOR_NAME=<git-username>
GIT_AUTHOR_EMAIL=<git-email>
GIT_COMMITTER_NAME=<git-username>
GIT_COMMITTER_EMAIL=<git-email>
EOF

# Agent SSH directory — ralph runs as uid 1001 (non-root); needs its own copy of
# the deploy key with matching ownership. The mount is read-only so we use absolute
# paths in the SSH config (not ~/) to avoid home dir ambiguity.
mkdir -p /opt/agentx/.agent-ssh
cp /root/.ssh/hostinger /opt/agentx/.agent-ssh/
chmod 700 /opt/agentx/.agent-ssh
chmod 600 /opt/agentx/.agent-ssh/hostinger
cat > /opt/agentx/.agent-ssh/config <<'EOF'
Host github.com
  IdentityFile /home/ralph/.ssh/hostinger
  StrictHostKeyChecking no
  UserKnownHostsFile /dev/null
EOF
chmod 600 /opt/agentx/.agent-ssh/config
chown -R 1001:1001 /opt/agentx/.agent-ssh

# Claude CLI — use your personal Anthropic account (no separate agent account needed)
npm install -g @anthropic-ai/claude-code
claude login

# Agent Claude config — container uses its own writable .claude dir (not root's).
# Copy OAuth credentials from the login above. Do NOT use ANTHROPIC_API_KEY;
# OAuth mode is more reliable and doesn't require managing API keys.
mkdir -p /opt/agentx/.agent-claude/todos /opt/agentx/.agent-claude/debug \
         /opt/agentx/.agent-claude/statsig /opt/agentx/.agent-claude/sessions
cp /root/.claude/.credentials.json /opt/agentx/.agent-claude/
cp /root/.claude/settings.json /opt/agentx/.agent-claude/ 2>/dev/null || true
chown -R 1001:1001 /opt/agentx/.agent-claude

# Smoke test — always run from main to avoid stale branch errors
git checkout main && git pull origin main
SCAFFOLD=/opt/agentx/scaffold ./ralph.sh plan 1
```

---

## Verification

```bash
docker ps          # Docker daemon running
claude --version   # Claude CLI installed and on PATH
```

Ralph smoke test success looks like:
```
[ralph] Auth mode: OAuth credentials file
[ralph] Creating branch: ralph/workspace-<timestamp>
[ralph] Starting loop...
[ralph] ITERATION 1
... (Claude output) ...
[ralph] Ralph Session Complete
```

---

## Re-running After a Failed Attempt

If a previous ralph run left the repo on a stale branch:

```bash
cd /opt/agentx && git checkout main && git pull origin main
SCAFFOLD=/opt/agentx/scaffold ./ralph.sh plan 1
```

## Watching Logs

From a second SSH session:

```bash
docker logs -f agentx-ralph-1
```
