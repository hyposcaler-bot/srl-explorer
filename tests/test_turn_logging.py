from __future__ import annotations

import json
from unittest.mock import MagicMock

from srl_explorer.turn_logging import TurnLogger


def test_start_turn_creates_directory(tmp_path):
    """start_turn() creates a turn_001 directory under the session dir."""
    logger = TurnLogger(tmp_path)
    logger.start_turn()
    assert (tmp_path / "turn_001").is_dir()


def test_file_sequence_numbering(tmp_path):
    """Log files are numbered sequentially and contain valid JSON."""
    logger = TurnLogger(tmp_path)
    logger.start_turn()

    logger.log_user_message("hello")

    msg = MagicMock()
    msg.content = "world"
    msg.tool_calls = None

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15

    logger.log_llm_response(msg, usage, finish_reason="stop", model="test-model")

    turn_dir = tmp_path / "turn_001"
    user_file = turn_dir / "00_user_message.json"
    llm_file = turn_dir / "01_llm_response_final.json"

    assert user_file.exists()
    assert llm_file.exists()

    # Both must be valid JSON
    json.loads(user_file.read_text())
    json.loads(llm_file.read_text())


def test_turn_number_increments(tmp_path):
    """Two start_turn() calls create turn_001 and turn_002; file_seq resets."""
    logger = TurnLogger(tmp_path)
    logger.start_turn()
    logger.log_user_message("first")
    assert logger.file_seq == 1

    logger.start_turn()
    assert logger.file_seq == 0
    assert (tmp_path / "turn_001").is_dir()
    assert (tmp_path / "turn_002").is_dir()


def test_session_summary(tmp_path):
    """update_session_summary writes correct counts to session_summary.json."""
    logger = TurnLogger(tmp_path)
    logger.start_turn()

    logger.log_tool_result(
        tool_call_id="tc_1",
        name="gnmic_get",
        result={"name": "leaf1"},
        duration_ms=42,
        error=None,
    )
    logger.update_session_summary()

    summary = json.loads((tmp_path / "session_summary.json").read_text())
    assert summary["turns"] == 1
    assert summary["total_tool_calls"] == 1
    assert summary["tool_call_counts"] == {"gnmic_get": 1}
    assert summary["errors"] == 0


def test_tool_result_tracks_errors(tmp_path):
    """log_tool_result with an error increments both errors and tool_call_counts."""
    logger = TurnLogger(tmp_path)
    logger.start_turn()

    logger.log_tool_result(
        tool_call_id="tc_1",
        name="gnmic_get",
        result=None,
        duration_ms=10,
        error="something broke",
    )

    assert logger.errors == 1
    assert logger.tool_call_counts["gnmic_get"] == 1


def test_log_failure_does_not_raise(tmp_path):
    """_write does not raise when turn_dir is None or unwritable."""
    logger = TurnLogger(tmp_path)
    # turn_dir is None before start_turn — should silently return
    logger._write({"test": True}, name_hint="test")

    # Set turn_dir to a path that cannot be written to
    logger.turn_dir = tmp_path / "no_such_parent" / "nested"
    logger._write({"test": True}, name_hint="test")
