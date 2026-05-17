"""Tests for src/listener.py — parsing, dispatch logic, and spend tracking."""

from __future__ import annotations

import email
import email.policy
import json
import textwrap
from email.message import EmailMessage
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from listener import (
    Config,
    dispatch_task,
    extract_cost_from_output,
    extract_spec,
    get_cumulative_cost,
    get_status,
    parse_subject,
    process_message,
    write_session_log,
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

    def test_includes_cumulative_spend(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / "logs").mkdir()
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        jsonl.write_text('{"cost_usd": 0.05, "cumulative_cost_usd": 0.05}\n')
        status = get_status(cfg)
        assert "Cumulative spend" in status


# ---------------------------------------------------------------------------
# write_session_log
# ---------------------------------------------------------------------------

class TestWriteSessionLog:
    def test_creates_json_file_in_logs_sessions(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        record = {
            "session_id": "test-session-id",
            "started_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:01:00+00:00",
            "duration_seconds": 60.0,
            "task_description": "deploy",
            "spec_preview": "# Spec",
            "sender": "user@example.com",
            "exit_code": 0,
            "timed_out": False,
            "output_tail": "done",
            "cost_usd": 0.01,
            "cumulative_cost_usd": 0.01,
        }
        write_session_log(cfg, record)

        session_file = tmp_path / "logs" / "sessions" / "test-session-id.json"
        assert session_file.exists()
        data = json.loads(session_file.read_text())
        assert data["session_id"] == "test-session-id"
        assert data["task_description"] == "deploy"
        assert data["exit_code"] == 0

    def test_appends_to_sessions_jsonl(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        for i, sid in enumerate(["id-1", "id-2"]):
            record = {
                "session_id": sid,
                "started_at": "2024-01-01T00:00:00+00:00",
                "completed_at": "2024-01-01T00:01:00+00:00",
                "duration_seconds": float(i),
                "task_description": f"task {i}",
                "spec_preview": "",
                "sender": "",
                "exit_code": 0,
                "timed_out": False,
                "output_tail": "",
                "cost_usd": 0.0,
                "cumulative_cost_usd": 0.0,
            }
            write_session_log(cfg, record)

        jsonl = tmp_path / "logs" / "sessions.jsonl"
        lines = [l for l in jsonl.read_text().splitlines() if l.strip()]
        assert len(lines) == 2
        first = json.loads(lines[0])
        assert first["session_id"] == "id-1"
        second = json.loads(lines[1])
        assert second["session_id"] == "id-2"

    def test_creates_logs_directory_if_missing(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert not (tmp_path / "logs").exists()
        record = {
            "session_id": "abc",
            "started_at": "2024-01-01T00:00:00+00:00",
            "completed_at": "2024-01-01T00:00:01+00:00",
            "duration_seconds": 1.0,
            "task_description": "",
            "spec_preview": "",
            "sender": "",
            "exit_code": 0,
            "timed_out": False,
            "output_tail": "",
            "cost_usd": 0.0,
            "cumulative_cost_usd": 0.0,
        }
        write_session_log(cfg, record)
        assert (tmp_path / "logs" / "sessions").is_dir()


# ---------------------------------------------------------------------------
# extract_cost_from_output
# ---------------------------------------------------------------------------

class TestExtractCostFromOutput:
    def test_extracts_cost_from_result_event(self) -> None:
        output = (
            '{"type": "system", "subtype": "init"}\n'
            '{"type": "assistant", "message": {"content": "hello"}}\n'
            '{"type": "result", "subtype": "success", "cost_usd": "0.012345"}\n'
        )
        cost = extract_cost_from_output(output)
        assert abs(cost - 0.012345) < 1e-9

    def test_sums_multiple_result_events(self) -> None:
        output = (
            '{"type": "result", "cost_usd": "0.01"}\n'
            '{"type": "result", "cost_usd": "0.02"}\n'
        )
        cost = extract_cost_from_output(output)
        assert abs(cost - 0.03) < 1e-9

    def test_ignores_non_json_lines(self) -> None:
        output = "not json\n{\"type\": \"result\", \"cost_usd\": \"0.005\"}\n"
        cost = extract_cost_from_output(output)
        assert abs(cost - 0.005) < 1e-9

    def test_returns_zero_when_no_result_events(self) -> None:
        output = '{"type": "assistant", "message": "hello"}\n'
        cost = extract_cost_from_output(output)
        assert cost == 0.0

    def test_returns_zero_on_empty_output(self) -> None:
        assert extract_cost_from_output("") == 0.0

    def test_handles_missing_cost_field(self) -> None:
        output = '{"type": "result", "subtype": "success"}\n'
        cost = extract_cost_from_output(output)
        assert cost == 0.0


# ---------------------------------------------------------------------------
# get_cumulative_cost
# ---------------------------------------------------------------------------

class TestGetCumulativeCost:
    def test_returns_zero_when_no_log_file(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        assert get_cumulative_cost(cfg) == 0.0

    def test_sums_cost_from_jsonl(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / "logs").mkdir()
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        jsonl.write_text(
            '{"cost_usd": 0.01}\n'
            '{"cost_usd": 0.02}\n'
            '{"cost_usd": 0.005}\n'
        )
        total = get_cumulative_cost(cfg)
        assert abs(total - 0.035) < 1e-9

    def test_skips_missing_cost_field(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / "logs").mkdir()
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        jsonl.write_text('{"task_description": "no cost field"}\n{"cost_usd": 0.1}\n')
        total = get_cumulative_cost(cfg)
        assert abs(total - 0.1) < 1e-9

    def test_skips_malformed_lines(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        (tmp_path / "logs").mkdir()
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        jsonl.write_text('not json\n{"cost_usd": 0.05}\n')
        total = get_cumulative_cost(cfg)
        assert abs(total - 0.05) < 1e-9


# ---------------------------------------------------------------------------
# dispatch_task
# ---------------------------------------------------------------------------

class TestDispatchTask:
    @pytest.mark.asyncio
    async def test_writes_task_to_implementation_plan_and_runs_ralph(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        spec = "# Deploy\n\nRun the thing."
        summary = await dispatch_task(cfg, spec, "deploy the thing")

        plan_file = tmp_path / "IMPLEMENTATION_PLAN.md"
        assert plan_file.exists()
        assert "Deploy" in plan_file.read_text()
        assert "deploy the thing" in summary
        assert "Ralph loop" in summary

    @pytest.mark.asyncio
    async def test_session_log_written_after_dispatch(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        await dispatch_task(cfg, "# Spec", "log test task", sender="tester@example.com")

        jsonl = tmp_path / "logs" / "sessions.jsonl"
        assert jsonl.exists()
        record = json.loads(jsonl.read_text().strip())
        assert record["task_description"] == "log test task"
        assert record["sender"] == "tester@example.com"
        assert record["exit_code"] == 0
        assert record["timed_out"] is False
        assert "session_id" in record
        assert "started_at" in record
        assert "completed_at" in record
        assert "duration_seconds" in record
        assert "cost_usd" in record
        assert "cumulative_cost_usd" in record

    @pytest.mark.asyncio
    async def test_session_log_spec_preview_truncated_at_500(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        long_spec = "x" * 1000
        await dispatch_task(cfg, long_spec, "big spec")

        jsonl = tmp_path / "logs" / "sessions.jsonl"
        record = json.loads(jsonl.read_text().strip())
        assert len(record["spec_preview"]) == 500

    @pytest.mark.asyncio
    async def test_cost_extracted_and_logged(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.042"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
        )
        await dispatch_task(cfg, "spec", "cost test")
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        record = json.loads(jsonl.read_text().strip())
        assert abs(record["cost_usd"] - 0.042) < 1e-9
        assert abs(record["cumulative_cost_usd"] - 0.042) < 1e-9

    @pytest.mark.asyncio
    async def test_cumulative_cost_accumulates(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.01"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
        )
        await dispatch_task(cfg, "spec", "run 1")
        await dispatch_task(cfg, "spec", "run 2")
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        lines = [json.loads(l) for l in jsonl.read_text().splitlines() if l.strip()]
        assert abs(lines[0]["cumulative_cost_usd"] - 0.01) < 1e-9
        assert abs(lines[1]["cumulative_cost_usd"] - 0.02) < 1e-9

    @pytest.mark.asyncio
    async def test_summary_includes_cost(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.007"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
        )
        summary = await dispatch_task(cfg, "spec", "cost summary test")
        assert "Cost:" in summary or "cost" in summary.lower()

    @pytest.mark.asyncio
    async def test_spend_ceiling_writes_stop_sentinel(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.10"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
            spend_ceiling_usd=0.05,
        )
        with patch("listener.send_reply", new_callable=AsyncMock):
            await dispatch_task(cfg, "spec", "expensive task")
        assert (tmp_path / ".stop").exists()

    @pytest.mark.asyncio
    async def test_spend_ceiling_sends_alert_email(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.10"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
            spend_ceiling_usd=0.05,
            spend_alert_email="admin@example.com",
        )
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await dispatch_task(cfg, "spec", "ceiling task")
        calls = [c for c in mock_reply.call_args_list if "ceiling" in str(c).lower() or "admin@example.com" in str(c)]
        assert len(calls) > 0

    @pytest.mark.asyncio
    async def test_spend_alert_threshold_sends_warning_without_stopping(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text(
            '#!/bin/bash\necho \'{"type":"result","cost_usd":"0.06"}\'\n'
        )
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
            spend_alert_threshold_usd=0.05,
            spend_alert_email="admin@example.com",
        )
        with patch("listener.send_reply", new_callable=AsyncMock) as mock_reply:
            await dispatch_task(cfg, "spec", "alert task")
        assert not (tmp_path / ".stop").exists()
        alert_calls = [c for c in mock_reply.call_args_list if "admin@example.com" in str(c)]
        assert len(alert_calls) > 0

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
    async def test_non_zero_exit_recorded_in_session_log(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nexit 2\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh,
        )
        await dispatch_task(cfg, "spec", "failing task")
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        record = json.loads(jsonl.read_text().strip())
        assert record["exit_code"] == 2
        assert record["timed_out"] is False

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

    @pytest.mark.asyncio
    async def test_timeout_recorded_in_session_log(self, tmp_path: Path) -> None:
        ralph_sh = tmp_path / "ralph.sh"
        ralph_sh.write_text("#!/bin/bash\nsleep 999\n")
        ralph_sh.chmod(0o755)
        cfg = Config(
            imap_host="x", imap_port=993, imap_user="u", imap_pass="p",
            smtp_host="x", smtp_port=465, smtp_user="u", smtp_pass="p",
            workspace=tmp_path, ralph_sh=ralph_sh, ralph_timeout=1,
        )
        await dispatch_task(cfg, "spec", "slow task")
        jsonl = tmp_path / "logs" / "sessions.jsonl"
        record = json.loads(jsonl.read_text().strip())
        assert record["timed_out"] is True
        assert record["exit_code"] is None


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
    async def test_task_dispatch_receives_sender(self, tmp_path: Path) -> None:
        cfg = make_config(tmp_path)
        raw = make_email("[task] build listener", "# Spec\n\nDo it.", "ralph@example.com")

        with (
            patch("listener.dispatch_task", new_callable=AsyncMock, return_value="done") as mock_dispatch,
            patch("listener.send_reply", new_callable=AsyncMock),
        ):
            await process_message(cfg, raw)

        _, kwargs = mock_dispatch.call_args
        assert kwargs.get("sender") == "ralph@example.com"

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

    def test_spend_ceiling_defaults_to_zero(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        cfg = Config.from_env()
        assert cfg.spend_ceiling_usd == 0.0
        assert cfg.spend_alert_threshold_usd == 0.0
        assert cfg.spend_alert_email == ""

    def test_spend_ceiling_loaded_from_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        monkeypatch.setenv("IMAP_USER", "u@example.com")
        monkeypatch.setenv("IMAP_PASS", "pass1")
        monkeypatch.setenv("SMTP_USER", "u@example.com")
        monkeypatch.setenv("SMTP_PASS", "pass2")
        monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
        monkeypatch.setenv("AGENTX_SPEND_CEILING_USD", "5.00")
        monkeypatch.setenv("AGENTX_SPEND_ALERT_USD", "3.00")
        monkeypatch.setenv("AGENTX_SPEND_ALERT_EMAIL", "admin@example.com")
        cfg = Config.from_env()
        assert cfg.spend_ceiling_usd == 5.0
        assert cfg.spend_alert_threshold_usd == 3.0
        assert cfg.spend_alert_email == "admin@example.com"
