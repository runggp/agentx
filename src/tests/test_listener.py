"""Tests for src/listener.py — parsing and dispatch logic."""

from __future__ import annotations

import email
import email.policy
import textwrap
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from listener import (
    Config,
    dispatch_task,
    extract_spec,
    get_status,
    parse_subject,
    process_message,
    write_stop_sentinel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(tmp_path: Path) -> Config:
    ralph_sh = tmp_path / "ralph.sh"
    ralph_sh.write_text("#!/bin/bash\necho done\n")
    ralph_sh.chmod(0o755)

    return Config(
        imap_host="imap.example.com",
        imap_port=993,
        imap_user="agent@example.com",
        imap_pass="secret",
        smtp_host="smtp.example.com",
        smtp_port=465,
        smtp_user="agent@example.com",
        smtp_pass="secret",
        workspace=tmp_path,
        ralph_sh=ralph_sh,
        poll_interval=5,
    )


def make_email(
    subject: str,
    body: str,
    from_addr: str = "user@example.com",
    md_attachment: str | None = None,
) -> bytes:
    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = "agent@example.com"
    msg["Subject"] = subject
    msg.set_content(body)
    if md_attachment is not None:
        msg.add_attachment(
            md_attachment.encode(),
            maintype="text",
            subtype="markdown",
            filename="spec.md",
        )
    return msg.as_bytes()


# ---------------------------------------------------------------------------
# parse_subject
# ---------------------------------------------------------------------------

class TestParseSubject:
    def test_task_with_description(self) -> None:
        prefix, desc = parse_subject("[task] deploy the harness")
        assert prefix == "task"
        assert desc == "deploy the harness"

    def test_stop(self) -> None:
        prefix, desc = parse_subject("[stop]")
        assert prefix == "stop"
        assert desc == ""

    def test_status(self) -> None:
        prefix, desc = parse_subject("[status]")
        assert prefix == "status"
        assert desc == ""

    def test_case_insensitive(self) -> None:
        prefix, _ = parse_subject("[TASK] something")
        assert prefix == "task"

    def test_unrecognized(self) -> None:
        prefix, raw = parse_subject("Hello world")
        assert prefix == ""
        assert raw == "Hello world"

    def test_task_no_description(self) -> None:
        prefix, desc = parse_subject("[task]")
        assert prefix == "task"
        assert desc == ""


# ---------------------------------------------------------------------------
# extract_spec
# ---------------------------------------------------------------------------

class TestExtractSpec:
    def test_plain_body(self) -> None:
        raw = make_email("[task] test", "# My Spec\n\nDo the thing.")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "My Spec" in spec
        assert "Do the thing" in spec

    def test_md_attachment_preferred_over_body(self) -> None:
        raw = make_email(
            "[task] test",
            "Ignore this body.",
            md_attachment="# Attachment Spec\n\nUse this.",
        )
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "Attachment Spec" in spec
        assert "Ignore this body" not in spec

    def test_empty_email(self) -> None:
        msg = EmailMessage()
        msg["From"] = "x@example.com"
        msg["Subject"] = "[task] empty"
        spec = extract_spec(msg)
        assert spec == ""

    def test_multipart_extracts_plain(self) -> None:
        raw = make_email("[task] multi", "Plain text spec here.")
        msg = email.message_from_bytes(raw, policy=email.policy.default)
        spec = extract_spec(msg)
        assert "Plain text spec here" in spec


# ---------------------------------------------------------------------------
# write_stop_sentinel
# ---------------------------------------------------------------------------

class TestWriteStopSentinel:
    def test_creates_file(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        write_stop_sentinel(cfg)
        stop_file = tmp_path / ".stop"
        assert stop_file.exists()
        assert "stop" in stop_file.read_text()


# ---------------------------------------------------------------------------
# get_status
# ---------------------------------------------------------------------------

class TestGetStatus:
    def test_no_stop_sentinel(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        status = get_status(cfg)
        assert "No stop sentinel" in status

    def test_with_stop_sentinel(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / ".stop").write_text("stop\n")
        status = get_status(cfg)
        assert "Stop sentinel is present" in status

    def test_includes_git_section(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        status = get_status(cfg)
        assert "Recent commits" in status or "Could not read git log" in status


# ---------------------------------------------------------------------------
# dispatch_task
# ---------------------------------------------------------------------------

class TestDispatchTask:
    @pytest.mark.asyncio
    async def test_writes_task_file_and_runs_ralph(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        spec = "# Deploy\n\nRun the thing."
        summary = await dispatch_task(cfg, spec, "deploy the thing")

        task_file = tmp_path / "TASK.md"
        assert task_file.exists()
        assert "Deploy" in task_file.read_text()
        assert "deploy the thing" in summary
        assert "Ralph loop" in summary

    @pytest.mark.asyncio
    async def test_non_zero_exit_noted_in_summary(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nexit 1\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x",
            imap_port=993,
            imap_user="u",
            imap_pass="p",
            smtp_host="x",
            smtp_port=465,
            smtp_user="u",
            smtp_pass="p",
            workspace=tmp_path,
            ralph_sh=ralph_sh,
        )
        summary = await dispatch_task(cfg, "spec", "desc")
        assert "exited with code 1" in summary

    @pytest.mark.asyncio
    async def test_writes_to_implementation_plan(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        plan = tmp_path / "IMPLEMENTATION_PLAN.md"
        plan.write_text("# Implementation Plan\n\n## Current Focus\n\nexisting task\n")
        await dispatch_task(cfg, "# Spec\n\nDo it.", "email task desc")
        content = plan.read_text()
        assert "email task desc" in content
        assert "existing task" in content

    @pytest.mark.asyncio
    async def test_timeout_kills_process_and_returns_message(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nsleep 999\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh, ralph_timeout=1,
        )
        summary = await dispatch_task(cfg, "spec", "slow task")
        assert "timed out" in summary


# ---------------------------------------------------------------------------
# process_message (integration-style with mocks)
# ---------------------------------------------------------------------------

class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_task_prefix_triggers_dispatch_and_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task] build listener", "# Spec\n\nDo it.", "user@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="Work done.") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock) as mock_reply,
        ):
            await process_message(cfg, raw)

        mock_dispatch.assert_awaited_once()
        mock_reply.assert_awaited_once()
        _, reply_to, _, body = mock_reply.call_args[0]
        assert "Work done" in body

    @pytest.mark.asyncio
    async def test_stop_prefix_writes_sentinel_and_replies(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[stop]", "halt please", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        assert (tmp_path / ".stop").exists()
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_status_prefix_sends_status_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[status]", "", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        mock_reply.assert_awaited_once()
        _, _, _, body = mock_reply.call_args[0]
        assert "agentx status" in body

    @pytest.mark.asyncio
    async def test_unrecognized_prefix_ignored(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("Hello there", "random email", "user@example.com")

        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)

        mock_reply.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_allowed_sender_passes(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["user@example.com"])},
        )
        raw = make_email("[status]", "", "user@example.com")
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_unauthorised_sender_rejected(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["allowed@example.com"])},
        )
        raw = make_email("[task] do something", "spec", "evil@example.com")
        with patch("listener.dispatch_task", new_callable=AsyncMock) as mock_dispatch:
            await process_message(cfg, raw)
        mock_dispatch.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_name_bracket_addr_format_parsed(self, tmp_path: Path) -> None:
        cfg = Config(
            **{**make_config(tmp_path).__dict__,
               "allowed_senders": frozenset(["user@example.com"])},
        )
        raw = make_email("[status]", "", "User Name <user@example.com>")
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await process_message(cfg, raw)
        mock_reply.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_task_with_empty_spec_sends_error_reply(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        msg = EmailMessage()
        msg["From"] = "user@example.com"
        msg["Subject"] = "[task] oops"
        raw = msg.as_bytes()

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock) as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock) as mock_reply,
        ):
            await process_message(cfg, raw)

        mock_dispatch.assert_not_awaited()
        mock_reply.assert_awaited_once()
        _, _, _, body = mock_reply.call_args[0]
        assert "Could not extract" in body


# ---------------------------------------------------------------------------
# Config.from_env
# ---------------------------------------------------------------------------

class TestConfigFromEnv:
    def test_requires_imap_user(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("IMAP_USER", raising=False)
        monkeypatch.delenv("IMAP_PASS", raising=False)
        monkeypatch.delenv("SMTP_USER", raising=False)
        monkeypatch.delenv("SMTP_PASS", raising=False)
        with pytest.raises(RuntimeError, match="IMAP_USER"):
            Config.from_env()

    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        cfg = Config.from_env()
        assert cfg.imap_user == "u@example.com"
        assert cfg.workspace == tmp_path

    def test_allowed_senders_parsed_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        monkeypatch.setenv("AGENTX_ALLOWED_SENDERS", "a@example.com, B@EXAMPLE.COM")
        cfg = Config.from_env()
        assert cfg.allowed_senders == frozenset(["a@example.com", "b@example.com"])
