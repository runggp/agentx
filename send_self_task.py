#!/usr/bin/env python3
"""
Send a task email to agentx@runggp.com to trigger the Ralph loop via the email listener.

Usage:
    uv run --env-file /opt/agentx/secrets.env send_self_task.py
    uv run --env-file /opt/agentx/secrets.env send_self_task.py --subject "[task] custom task" --spec specs/my-spec.md

Environment variables (from secrets.env):
    SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS
    AGENTX_TO  (optional, defaults to SMTP_USER i.e. agentx@runggp.com)
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib

DEFAULT_SUBJECT = "[task] deploy this harness to VPS"

DEFAULT_SPEC = """\
# Deploy agentx harness to VPS

## Goal
Verify the agentx harness is fully operational on the Hostinger KVM 4 VPS and the
email-triggered loop works end-to-end.

## Acceptance criteria
- [ ] `ralph.sh` launches Docker container and runs at least one Claude iteration
- [ ] `src/listener.py` polls IMAP and processes incoming task emails
- [ ] A task email sent to agentx@runggp.com triggers the loop and receives a reply
- [ ] Session logs written to `logs/sessions/` per invocation
- [ ] All tests pass: `uv run --dev pytest --tb=short -v`

## Constraints / out of scope
- Do not modify Docker base image or scaffold core scripts
- Do not push to main; agent commits to branch only
- VPS credentials come from `secrets.env`; never bake into Docker

## Context
- Harness repo: /opt/agentx on VPS
- Listener runs on VPS host: `uv run --env-file /opt/agentx/secrets.env src/listener.py`
- Ralph loop: `./ralph.sh` (dockerised, Claude API)
- Compose file: `vps-compose.yml`
"""


async def send(smtp_host: str, smtp_port: int, smtp_user: str, smtp_pass: str,
               to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = smtp_user
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    await aiosmtplib.send(
        msg,
        hostname=smtp_host,
        port=smtp_port,
        username=smtp_user,
        password=smtp_pass,
        use_tls=True,
    )
    print(f"Sent: {subject!r} -> {to_addr}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Send a task email to agentx")
    parser.add_argument("--subject", default=DEFAULT_SUBJECT, help="Email subject (include [task] prefix)")
    parser.add_argument("--spec", default=None, help="Path to markdown spec file (default: built-in deploy spec)")
    args = parser.parse_args()

    def require(key: str) -> str:
        val = os.environ.get(key, "")
        if not val:
            print(f"Error: required env var {key!r} is not set", file=sys.stderr)
            sys.exit(1)
        return val

    smtp_host = os.environ.get("SMTP_HOST", "smtp.hostinger.com")
    smtp_port = int(os.environ.get("SMTP_PORT", "465"))
    smtp_user = require("SMTP_USER")
    smtp_pass = require("SMTP_PASS")
    to_addr = os.environ.get("AGENTX_TO", smtp_user)

    if args.spec:
        body = Path(args.spec).read_text(encoding="utf-8")
    else:
        body = DEFAULT_SPEC

    asyncio.run(send(smtp_host, smtp_port, smtp_user, smtp_pass, to_addr, args.subject, body))


if __name__ == "__main__":
    main()
