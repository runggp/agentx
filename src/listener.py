"""
agentx email listener

Polls agentx@runggp.com IMAP inbox for task emails, dispatches ralph.sh,
and replies with a work summary.

Usage:
    uv run --env-file /opt/agentx/secrets.env src/listener.py

Subject prefixes:
    [task] <description>   — extract spec from body/.md attachment, run ralph
    [stop]                 — write .stop sentinel to workspace; loop exits cleanly
    [status]               — reply with current loop state and recent git commits
"""

from __future__ import annotations

import asyncio
import datetime
import email
import email.policy
import json
import logging
import os
import subprocess
import sys
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

import aioimaplib
import aiosmtplib

log = logging.getLogger("agentx.listener")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    imap_host: str
    imap_port: int
    imap_user: str
    imap_pass: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    workspace: Path
    ralph_sh: Path
    poll_interval: int = 30
    allowed_senders: frozenset[str] = frozenset()
    ralph_timeout: int = 1800

    @classmethod
    def from_env(cls) -> "Config":
        def require(key: str) -> str:
            val = os.environ.get(key, "")
            if not val:
                raise RuntimeError(f"Required env var {key!r} is not set")
            return val

        workspace = Path(os.environ.get("WORKSPACE_PATH", "/opt/agentx"))
        ralph_sh = Path(os.environ.get("RALPH_SH", str(workspace / "ralph.sh")))

        raw_senders = os.environ.get("AGENTX_ALLOWED_SENDERS", "")
        allowed_senders: frozenset[str] = frozenset(
            s.strip().lower() for s in raw_senders.split(",") if s.strip()
        )

        return cls(
            imap_host=os.environ.get("IMAP_HOST", "imap.hostinger.com"),
            imap_port=int(os.environ.get("IMAP_PORT", "993")),
            imap_user=require("IMAP_USER"),
            imap_pass=require("IMAP_PASS"),
            smtp_host=os.environ.get("SMTP_HOST", "smtp.hostinger.com"),
            smtp_port=int(os.environ.get("SMTP_PORT", "465")),
            smtp_user=require("SMTP_USER"),
            smtp_pass=require("SMTP_PASS"),
            workspace=workspace,
            ralph_sh=ralph_sh,
            poll_interval=int(os.environ.get("AGENTX_POLL_INTERVAL", "30")),
            allowed_senders=allowed_senders,
            ralph_timeout=int(os.environ.get("AGENTX_RALPH_TIMEOUT", "1800")),
        )


# ---------------------------------------------------------------------------
# Email parsing
# ---------------------------------------------------------------------------

def extract_spec(msg: email.message.Message) -> str:
    """Return markdown spec text from an email.

    Preference order:
    1. First .md attachment
    2. text/plain body
    3. text/html body stripped to plain text (fallback)
    """
    plain_body: str | None = None
    html_body: str | None = None

    for part in msg.walk():
        content_type = part.get_content_type()
        filename = part.get_filename() or ""
        disposition = str(part.get("Content-Disposition", ""))

        if "attachment" in disposition and filename.endswith(".md"):
            payload = part.get_payload(decode=True)
            if payload:
                return payload.decode("utf-8", errors="replace").strip()

        if content_type == "text/plain" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if payload:
                plain_body = payload.decode("utf-8", errors="replace").strip()

        elif content_type == "text/html" and "attachment" not in disposition:
            payload = part.get_payload(decode=True)
            if payload:
                html_body = payload.decode("utf-8", errors="replace").strip()

    if plain_body:
        return plain_body
    if html_body:
        import re
        text = re.sub(r"<[^>]+>", "", html_body)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
    return ""


def parse_subject(raw_subject: str) -> tuple[str, str]:
    """Return (prefix, description) from a subject line.

    Examples:
        "[task] deploy harness" -> ("task", "deploy harness")
        "[stop]"                -> ("stop", "")
        "[status]"              -> ("status", "")
    """
    import re
    m = re.match(r"^\[(\w+)\]\s*(.*)", raw_subject.strip(), re.IGNORECASE)
    if m:
        return m.group(1).lower(), m.group(2).strip()
    return "", raw_subject.strip()


# ---------------------------------------------------------------------------
# Session logging
# ---------------------------------------------------------------------------

def write_session_log(cfg: Config, record: dict) -> None:  # type: ignore[type-arg]
    """Write a JSON session record to logs/sessions/<id>.json and append to sessions.jsonl.

    Schema:
        session_id       — UUID4 string
        started_at       — ISO-8601 UTC timestamp
        completed_at     — ISO-8601 UTC timestamp
        duration_seconds — float elapsed time
        task_description — human-readable task name from email subject
        spec_preview     — first 500 chars of spec (full spec may be large)
        sender           — email address that triggered the session
        exit_code        — ralph.sh exit code (null on timeout)
        timed_out        — true if ralph was killed due to timeout
        output_tail      — last 100 lines of ralph stdout+stderr

    Future agent iterations can read sessions.jsonl to understand what has been
    attempted, how long tasks took, and what exit codes were produced.
    """
    log_dir = cfg.workspace / "logs" / "sessions"
    log_dir.mkdir(parents=True, exist_ok=True)

    session_id: str = record["session_id"]
    session_file = log_dir / f"{session_id}.json"
    session_file.write_text(json.dumps(record, indent=2), encoding="utf-8")

    jsonl_file = cfg.workspace / "logs" / "sessions.jsonl"
    with jsonl_file.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")

    log.info("Session log written to %s", session_file)


# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

async def dispatch_task(cfg: Config, spec: str, description: str, sender: str = "") -> str:
    """Write spec into IMPLEMENTATION_PLAN.md and run ralph.sh.

    The spec is prepended as a new task so ralph's normal plan-reading
    flow picks it up on the next iteration.

    Returns a human-readable work summary string.
    """
    plan_file = cfg.workspace / "IMPLEMENTATION_PLAN.md"
    task_block = f"- [ ] **Email task:** {description}\n\n{spec}\n\n"
    if plan_file.exists():
        existing = plan_file.read_text(encoding="utf-8")
        # Insert after the "## Current Focus" heading
        marker = "## Current Focus"
        if marker in existing:
            plan_file.write_text(
                existing.replace(marker, f"{marker}\n\n{task_block}", 1),
                encoding="utf-8",
            )
        else:
            plan_file.write_text(task_block + existing, encoding="utf-8")
    else:
        plan_file.write_text(
            f"# Implementation Plan\n\n## Current Focus\n\n{task_block}",
            encoding="utf-8",
        )
    log.info("Wrote task to %s", plan_file)

    env = {**os.environ, "WORKSPACE_PATH": str(cfg.workspace)}
    log.info("Launching ralph.sh at %s", cfg.ralph_sh)

    session_id = str(uuid.uuid4())
    started_at = datetime.datetime.now(datetime.timezone.utc)

    proc = await asyncio.create_subprocess_exec(
        str(cfg.ralph_sh),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=env,
        cwd=str(cfg.workspace),
    )
    timed_out = False
    exit_code: int | None = None
    output = ""
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=cfg.ralph_timeout)
        output = stdout.decode("utf-8", errors="replace") if stdout else ""
        exit_code = proc.returncode
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        timed_out = True
        log.error("ralph.sh timed out after %ds", cfg.ralph_timeout)

    completed_at = datetime.datetime.now(datetime.timezone.utc)
    duration = (completed_at - started_at).total_seconds()

    record: dict = {  # type: ignore[type-arg]
        "session_id": session_id,
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "duration_seconds": duration,
        "task_description": description,
        "spec_preview": spec[:500],
        "sender": sender,
        "exit_code": exit_code,
        "timed_out": timed_out,
        "output_tail": "\n".join(output.splitlines()[-100:]),
    }
    write_session_log(cfg, record)

    if timed_out:
        return f"Ralph loop timed out after {cfg.ralph_timeout // 60} minutes.\n\nTask: {description}"

    resolved_exit = exit_code or 0
    status = "completed" if resolved_exit == 0 else f"exited with code {resolved_exit}"
    summary = (
        f"Ralph loop {status}.\n\n"
        f"Task: {description}\n\n"
        f"--- Loop output (last 100 lines) ---\n"
        + "\n".join(output.splitlines()[-100:])
    )
    log.info("Ralph finished (exit=%d)", resolved_exit)
    return summary


def get_status(cfg: Config) -> str:
    """Return current loop state and recent git commits."""
    lines: list[str] = ["agentx status\n"]

    stop_file = cfg.workspace / ".stop"
    if stop_file.exists():
        lines.append("Stop sentinel is present — loop will exit after current iteration.\n")
    else:
        lines.append("No stop sentinel.\n")

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=str(cfg.workspace),
            capture_output=True,
            text=True,
            timeout=10,
        )
        lines.append("\nRecent commits:\n")
        lines.append(result.stdout or "(none)")
    except Exception as exc:
        lines.append(f"\nCould not read git log: {exc}")

    return "\n".join(lines)


def write_stop_sentinel(cfg: Config) -> None:
    stop_file = cfg.workspace / ".stop"
    stop_file.write_text("stop\n", encoding="utf-8")
    log.info("Wrote stop sentinel to %s", stop_file)


# ---------------------------------------------------------------------------
# SMTP reply
# ---------------------------------------------------------------------------

async def send_reply(cfg: Config, to_addr: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = cfg.smtp_user
    msg["To"] = to_addr
    msg["Subject"] = f"Re: {subject}"
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=cfg.smtp_host,
            port=cfg.smtp_port,
            username=cfg.smtp_user,
            password=cfg.smtp_pass,
            use_tls=True,
        )
        log.info("Replied to %s", to_addr)
    except Exception as exc:
        log.error("Failed to send reply to %s: %s", to_addr, exc)


# ---------------------------------------------------------------------------
# IMAP polling
# ---------------------------------------------------------------------------

async def process_message(cfg: Config, raw: bytes) -> None:
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    from_addr = str(msg.get("From", ""))
    subject = str(msg.get("Subject", ""))

    log.info("Processing message from=%r subject=%r", from_addr, subject)

    if cfg.allowed_senders:
        import re as _re
        # Extract bare address from "Name <addr>" format
        m = _re.search(r"<([^>]+)>", from_addr)
        bare = (m.group(1) if m else from_addr).lower().strip()
        if bare not in cfg.allowed_senders:
            log.warning("Rejected message from unauthorised sender %r", from_addr)
            return

    prefix, description = parse_subject(subject)

    if prefix == "task":
        spec = extract_spec(msg)
        if not spec:
            reply_body = "Could not extract a spec from your email. Please include a markdown spec in the body or attach a .md file."
        else:
            reply_body = await dispatch_task(cfg, spec, description, sender=from_addr)
        await send_reply(cfg, from_addr, subject, reply_body)

    elif prefix == "stop":
        write_stop_sentinel(cfg)
        await send_reply(cfg, from_addr, subject, "Stop sentinel written. The loop will exit cleanly after its current iteration.")

    elif prefix == "status":
        status_body = get_status(cfg)
        await send_reply(cfg, from_addr, subject, status_body)

    else:
        log.debug("Ignoring message with unrecognized prefix %r", prefix)


async def poll_once(cfg: Config, imap: aioimaplib.IMAP4_SSL) -> None:
    """Search for UNSEEN messages and process each one."""
    status, data = await imap.uid("search", "UNSEEN")
    if status != "OK":
        log.warning("IMAP SEARCH failed: %s %s", status, data)
        return

    uid_list_raw = data[0].decode() if isinstance(data[0], bytes) else str(data[0])
    uids = [u for u in uid_list_raw.split() if u]
    if not uids:
        return

    log.info("Found %d unseen message(s)", len(uids))

    for uid in uids:
        try:
            fetch_status, fetch_data = await imap.uid("fetch", uid, "(RFC822)")
            if fetch_status != "OK":
                log.warning("FETCH failed for uid %s: %s", uid, fetch_status)
                continue

            # aioimaplib returns [metadata_line, message_bytes, b')']
            # The actual RFC822 body is the largest bytes item in the response.
            raw: bytes | None = None
            candidates = [item for item in fetch_data if isinstance(item, bytes) and item != b")"]
            if candidates:
                raw = max(candidates, key=len)

            if not raw:
                log.warning("No body data for uid %s", uid)
                continue

            await process_message(cfg, raw)

            await imap.uid("store", uid, "+FLAGS", r"(\Seen)")

        except Exception as exc:
            log.exception("Error processing uid %s: %s", uid, exc)


async def run_listener(cfg: Config) -> None:
    log.info("Connecting to IMAP %s:%d as %s", cfg.imap_host, cfg.imap_port, cfg.imap_user)

    while True:
        try:
            imap = aioimaplib.IMAP4_SSL(host=cfg.imap_host, port=cfg.imap_port)
            await imap.wait_hello_from_server()
            await imap.login(cfg.imap_user, cfg.imap_pass)
            await imap.select("INBOX")
            log.info("IMAP connected; polling every %ds", cfg.poll_interval)

            while True:
                await poll_once(cfg, imap)
                await asyncio.sleep(cfg.poll_interval)

        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error("IMAP error: %s — reconnecting in 60s", exc)
            await asyncio.sleep(60)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    try:
        cfg = Config.from_env()
    except RuntimeError as exc:
        log.error("Configuration error: %s", exc)
        sys.exit(1)

    log.info("agentx listener starting (workspace=%s)", cfg.workspace)

    try:
        asyncio.run(run_listener(cfg))
    except KeyboardInterrupt:
        log.info("Shutting down")


if __name__ == "__main__":
    main()
