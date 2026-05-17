"""
agentx task sender

Sends a [task] email to the agentx inbox to trigger a new Ralph loop.

Usage:
    uv run --env-file /opt/agentx/secrets.env src/send_task.py "<description>" [spec.md]
    echo "spec body" | uv run --env-file /opt/agentx/secrets.env src/send_task.py "<description>"

Note: if AGENTX_ALLOWED_SENDERS is set it must include SMTP_USER for self-sent
tasks to be accepted by the listener.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from email.message import EmailMessage
from pathlib import Path

import aiosmtplib

from listener import Config

log = logging.getLogger("agentx.send_task")


async def send_task(cfg: Config, description: str, spec: str) -> None:
    """Send a [task] email to the agentx inbox (cfg.imap_user)."""
    msg = EmailMessage()
    msg["From"] = cfg.smtp_user
    msg["To"] = cfg.imap_user
    msg["Subject"] = f"[task] {description}"
    msg.set_content(spec)

    await aiosmtplib.send(
        msg,
        hostname=cfg.smtp_host,
        port=cfg.smtp_port,
        username=cfg.smtp_user,
        password=cfg.smtp_pass,
        use_tls=True,
    )
    log.info("Task email sent to %s: [task] %s", cfg.imap_user, description)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    args = sys.argv[1:]
    if not args:
        print("Usage: send_task.py <description> [spec.md]", file=sys.stderr)
        sys.exit(1)

    description = args[0]

    if len(args) >= 2:
        spec = Path(args[1]).read_text(encoding="utf-8").strip()
    else:
        spec = sys.stdin.read().strip()

    if not spec:
        print("Error: spec body is empty", file=sys.stderr)
        sys.exit(1)

    try:
        cfg = Config.from_env()
    except RuntimeError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        sys.exit(1)

    async def _run() -> None:
        await send_task(cfg, description, spec)
        print(f"Task email sent to {cfg.imap_user}: [task] {description}")

    try:
        asyncio.run(_run())
    except Exception as exc:
        print(f"Failed to send task email: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
