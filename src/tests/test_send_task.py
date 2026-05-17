"""Tests for src/send_task.py — task email dispatch."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from listener import Config
from send_task import send_task


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
        smtp_user="sender@example.com",
        smtp_pass="smtpsecret",
        workspace=tmp_path,
        ralph_sh=ralph_sh,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_send_task_subject_has_task_prefix(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "deploy harness", "# Deploy\nRun docker compose up")
        msg = mock_send.call_args.args[0]
        assert msg["Subject"] == "[task] deploy harness"


@pytest.mark.asyncio
async def test_send_task_to_address_is_imap_user(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "self task", "spec body")
        msg = mock_send.call_args.args[0]
        assert msg["To"] == cfg.imap_user


@pytest.mark.asyncio
async def test_send_task_from_address_is_smtp_user(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "task", "spec")
        msg = mock_send.call_args.args[0]
        assert msg["From"] == cfg.smtp_user


@pytest.mark.asyncio
async def test_send_task_uses_smtp_credentials(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "task", "spec")
        kw = mock_send.call_args.kwargs
        assert kw["hostname"] == cfg.smtp_host
        assert kw["port"] == cfg.smtp_port
        assert kw["username"] == cfg.smtp_user
        assert kw["password"] == cfg.smtp_pass
        assert kw["use_tls"] is True


@pytest.mark.asyncio
async def test_send_task_description_preserved(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "install ollama on VPS", "spec content")
        msg = mock_send.call_args.args[0]
        assert msg["Subject"] == "[task] install ollama on VPS"


@pytest.mark.asyncio
async def test_send_task_calls_aiosmtplib_once(tmp_path: Path) -> None:
    cfg = make_config(tmp_path)
    with patch("send_task.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
        await send_task(cfg, "task", "spec")
        assert mock_send.call_count == 1
