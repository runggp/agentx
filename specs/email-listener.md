# Email Listener System Spec

## Overview

The email listener is the primary trigger mechanism for the VPS-hosted agent. It monitors `agentx@runggp.com` for incoming task specifications, extracts and validates them, runs the Ralph loop in isolated workspaces, and replies with execution results.

## Architecture

### Core Components

- **`src/listener.py`** - IMAP IDLE listener (main entry point)
- **`src/parser.py`** - Email content extraction and validation
- **`src/runner.py`** - Ralph loop execution wrapper
- **`src/responder.py`** - SMTP reply sender
- **`src/workspace.py`** - Workspace isolation and cleanup

### Event Loop Structure

```python
async def main():
    while True:
        async with IMAPClient() as imap:
            await imap.idle()  # Wait for new messages
            messages = await imap.fetch_new()
            for msg in messages:
                task = await parse_task_spec(msg)
                if task.valid:
                    workspace = create_workspace(task.id)
                    result = await run_ralph_loop(workspace, task.spec)
                    await send_reply(msg.sender, result)
                    cleanup_workspace(workspace)
```

## IMAP Listener (`src/listener.py`)

### Connection Strategy

- Use `aioimaplib` with IDLE command for real-time message detection
- Fallback to polling every 60 seconds if IDLE fails
- Automatic reconnection with exponential backoff (1s, 2s, 4s, 8s, max 60s)
- Connection timeout: 30 seconds
- Idle timeout: 29 minutes (refresh connection before 30min server timeout)

### Message Processing

```python
async def process_new_messages(imap_client):
    """Process all unread messages in INBOX"""
    messages = await imap_client.search('UNSEEN')
    for msg_id in messages:
        try:
            email = await fetch_email(imap_client, msg_id)
            if is_task_email(email):
                await handle_task_email(email)
                await mark_as_read(imap_client, msg_id)
        except Exception as e:
            log_error(f"Failed to process message {msg_id}: {e}")
```

### Error Handling

- Connection failures: log and retry with backoff
- Malformed emails: reply with error message, mark as read
- Authentication failures: log and exit (require manual intervention)
- Rate limit exceeded: temporary pause, then resume

## Email Parsing (`src/parser.py`)

### Task Email Detection

Subject must match pattern: `^\\[task\\]\\s+(.+)$`

Authorized senders (Phase 1 allowlist):
- `your-email@domain.com` (replace with actual authorized email)
- Additional emails can be added to environment variable `AUTHORIZED_SENDERS` (comma-separated)

### Spec Extraction Priority

1. First `.md` attachment (preferred)
2. Markdown code block in plain text body: ```markdown ... ```
3. Plain text body treated as markdown (fallback)

### Validation Rules

```python
def validate_task_spec(spec_content: str) -> TaskValidation:
    """Validate extracted task specification"""
    if len(spec_content.strip()) < 50:
        return TaskValidation(valid=False, error="Spec too short (min 50 chars)")

    if len(spec_content) > 10000:
        return TaskValidation(valid=False, error="Spec too long (max 10KB)")

    # Check for required sections (flexible)
    has_goal = bool(re.search(r'(^|\n)#+\s*(goal|objective|task)', spec_content, re.I))
    if not has_goal:
        log_warning("Spec missing clear goal section")

    return TaskValidation(valid=True, spec=spec_content)
```

## Workspace Isolation (`src/workspace.py`)

### Workspace Creation

Each task gets an isolated workspace directory:
```
/tmp/agentx-workspaces/
├── task-{timestamp}-{hash}/
│   ├── .git/                    # Fresh repo clone
│   ├── TASK_SPEC.md            # Extracted task specification
│   ├── IMPLEMENTATION_PLAN.md  # Empty template
│   └── specs/                  # Copied from base repo
```

### Base Repository Setup

```python
async def create_workspace(task_id: str) -> WorkspacePath:
    """Create isolated workspace for task execution"""
    workspace_dir = f"/tmp/agentx-workspaces/task-{task_id}"

    # Clone base repository (current workspace)
    await subprocess.run([
        "git", "clone", "/home/ralph/workspace", workspace_dir
    ], check=True)

    # Create fresh branch
    branch_name = f"ralph/task-{task_id}-{int(time.time())}"
    await git_checkout_new_branch(workspace_dir, branch_name)

    return WorkspacePath(path=workspace_dir, branch=branch_name)
```

### Cleanup Policy

- Workspaces older than 24 hours: automatic deletion
- Failed tasks: preserve for 6 hours for debugging
- Successful tasks: preserve until reply sent, then delete

## Ralph Loop Execution (`src/runner.py`)

### Execution Strategy

Run Ralph via subprocess, capturing all output:

```python
async def run_ralph_loop(workspace: WorkspacePath, spec: str) -> ExecutionResult:
    """Execute Ralph loop in isolated workspace"""

    # Write task spec to workspace
    spec_path = workspace.path / "TASK_SPEC.md"
    await write_file(spec_path, spec)

    # Set environment
    env = {
        **os.environ,
        "WORKSPACE_PATH": str(workspace.path),
        "RALPH_MAX_ITERATIONS": "10",
        "RALPH_MODE": "build"
    }

    # Execute via ralph.sh
    cmd = ["/home/ralph/workspace/ralph.sh"]
    process = await subprocess.create_subprocess_exec(
        *cmd,
        cwd=workspace.path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    stdout, _ = await process.communicate(timeout=1800)  # 30min timeout

    return ExecutionResult(
        success=process.returncode == 0,
        output=stdout.decode('utf-8', errors='replace'),
        branch=workspace.branch,
        workspace=workspace.path
    )
```

### Output Capture

Capture and structure:
- Raw stdout/stderr from Ralph loop
- Git commit hashes and messages
- Final git diff summary
- Execution duration and resource usage

## Reply Generation (`src/responder.py`)

### Reply Format

```python
def format_reply(task_email: Email, result: ExecutionResult) -> str:
    """Format execution result as email reply"""

    status = "✅ COMPLETED" if result.success else "❌ FAILED"

    return f"""
Subject: Re: {task_email.subject} - {status}

## Execution Summary

**Status:** {status}
**Duration:** {result.duration}
**Branch:** {result.branch}
**Commits:** {len(result.commits)}

## Task Specification
{result.original_spec[:200]}...

## Final Output
{result.output[-1000:]}  # Last 1KB of output

## Next Steps
{'Your task has been completed. Review the changes and merge if satisfied.' if result.success else 'The task failed. Please review the output and adjust your specification.'}

---
Generated by AgentX Email Listener v{VERSION}
"""
```

### SMTP Configuration

Use `aiosmtplib` with Hostinger SMTP:
- Host: `smtp.hostinger.com`
- Port: 465 (SSL/TLS)
- Authentication: `agentx@runggp.com` credentials from environment

### Delivery Handling

```python
async def send_reply(to_address: str, content: str) -> bool:
    """Send reply email with retry logic"""

    for attempt in range(3):
        try:
            async with aiosmtplib.SMTP(hostname=SMTP_HOST, port=SMTP_PORT, use_tls=True) as smtp:
                await smtp.login(SMTP_USER, SMTP_PASS)
                await smtp.send_message(message)
                return True
        except Exception as e:
            if attempt == 2:  # Last attempt
                log_error(f"Failed to send reply after 3 attempts: {e}")
                return False
            await asyncio.sleep(2 ** attempt)  # Exponential backoff
```

## Security & Authorization

### Sender Validation

```python
def is_authorized_sender(email_address: str) -> bool:
    """Check if sender is authorized to submit tasks"""
    authorized = os.getenv('AGENTX_ALLOWED_SENDERS', '').split(',')
    return email_address.lower().strip() in [addr.lower().strip() for addr in authorized if addr.strip()]
```

### Content Sanitization

- Strip HTML from email bodies
- Limit attachment size to 1MB
- Scan for obvious prompt injection attempts
- Log all incoming task requests for audit

### Rate Limiting

- Max 5 task emails per hour per sender
- Max 20 task emails per day total
- Temporary sender blacklist for obvious abuse

## Configuration & Environment

### Required Environment Variables

```bash
# Email credentials (from secrets.env)
IMAP_HOST=imap.hostinger.com
IMAP_PORT=993
IMAP_USER=agentx@runggp.com
IMAP_PASS=your_password

SMTP_HOST=smtp.hostinger.com
SMTP_PORT=465
SMTP_USER=agentx@runggp.com
SMTP_PASS=your_password

# Agent configuration
ANTHROPIC_API_KEY=sk-ant-...
AGENTX_ALLOWED_SENDERS=user@example.com,admin@company.com
RALPH_MAX_ITERATIONS=10
AGENTX_LOG_FILE=/var/log/agentx/listener.log
```

### Logging Configuration

Structure logs as JSON for machine readability:

Use stdlib `logging` with a JSON formatter. Each log record emitted as a single JSON line to stdout (and optionally to a log file via `AGENTX_LOG_FILE`):

```python
import json, logging, time

class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                           "level": record.levelname, "event": record.getMessage(),
                           **getattr(record, "extra", {})})
```

## Deployment & Monitoring

### Service Management

Run as systemd service on VPS:
```ini
[Unit]
Description=AgentX Email Listener
After=docker.service

[Service]
Type=simple
ExecStart=uv run --env-file /opt/agentx/secrets.env src/listener.py
Restart=always
RestartSec=10
User=ralph

[Install]
WantedBy=multi-user.target
```

### Health Checks

- Log heartbeat every 5 minutes when idle
- Expose simple HTTP endpoint for external monitoring
- Email alert if listener down for >10 minutes

### Metrics Collection

Track key metrics in logs:
- Tasks processed per day
- Success/failure rates
- Average execution duration
- Queue depth and processing lag