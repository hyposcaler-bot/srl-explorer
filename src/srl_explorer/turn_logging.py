from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _now() -> str:
    t = datetime.now(timezone.utc)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


class TurnLogger:
    def __init__(self, session_dir: Path) -> None:
        self.session_dir = session_dir
        self.session_id = session_dir.name
        self.turn_number = 0
        self.file_seq = 0
        self.turn_dir: Path | None = None

        self.started_at = _now()
        self.total_tool_calls = 0
        self.tool_call_counts: dict[str, int] = {}
        self.total_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }
        self.errors = 0
        self.model: str = ""

    def start_turn(self) -> None:
        self.turn_number += 1
        self.file_seq = 0
        self.turn_dir = self.session_dir / f"turn_{self.turn_number:03d}"
        try:
            self.turn_dir.mkdir(parents=True, exist_ok=True)
        except Exception as e:
            print(f"Warning: failed to create turn dir: {e}")

    def log_user_message(self, content: str) -> None:
        self._write(
            {
                "type": "user_message",
                "timestamp": _now(),
                "content": content,
            },
            name_hint="user_message",
        )

    def log_llm_response(
        self,
        message: Any,
        usage: Any,
        finish_reason: str,
        model: str,
    ) -> None:
        self.model = model
        is_final = finish_reason == "stop"

        tool_calls_data = None
        if message.tool_calls:
            tool_calls_data = []
            for tc in message.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except (json.JSONDecodeError, TypeError):
                    args = tc.function.arguments
                tool_calls_data.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": args,
                    }
                )

        usage_data = None
        if usage:
            usage_data = {
                "prompt_tokens": usage.prompt_tokens,
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            }
            self.total_usage["prompt_tokens"] += usage.prompt_tokens
            self.total_usage["completion_tokens"] += usage.completion_tokens
            self.total_usage["total_tokens"] += usage.total_tokens

        record = {
            "type": "llm_response_final" if is_final else "llm_response",
            "timestamp": _now(),
            "content": message.content,
            "tool_calls": tool_calls_data,
            "model": model,
            "usage": usage_data,
            "finish_reason": finish_reason,
        }

        suffix = "_final" if is_final else ""
        self._write(record, name_hint=f"llm_response{suffix}")

    def log_reasoning(self, content: str) -> None:
        self._write(
            {
                "type": "reasoning",
                "timestamp": _now(),
                "content": content,
            },
            name_hint="llm_reasoning",
        )

    def log_tool_call(
        self, tool_call_id: str, name: str, arguments: dict
    ) -> None:
        self._write(
            {
                "type": "tool_call",
                "timestamp": _now(),
                "tool_call_id": tool_call_id,
                "name": name,
                "arguments": arguments,
            },
            name_hint=f"tool_call_{name}",
        )

    def log_tool_result(
        self,
        tool_call_id: str,
        name: str,
        result: Any,
        duration_ms: int,
        error: str | None,
    ) -> None:
        self._write(
            {
                "type": "tool_result",
                "timestamp": _now(),
                "tool_call_id": tool_call_id,
                "name": name,
                "duration_ms": duration_ms,
                "success": error is None,
                "result": result,
                "error": error,
            },
            name_hint=f"tool_result_{name}",
        )

        self.total_tool_calls += 1
        self.tool_call_counts[name] = self.tool_call_counts.get(name, 0) + 1
        if error:
            self.errors += 1

    def update_session_summary(self) -> None:
        summary = {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "model": self.model,
            "turns": self.turn_number,
            "total_tool_calls": self.total_tool_calls,
            "total_usage": self.total_usage,
            "tool_call_counts": self.tool_call_counts,
            "errors": self.errors,
        }
        try:
            path = self.session_dir / "session_summary.json"
            with open(path, "w") as f:
                json.dump(summary, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: failed to write session summary: {e}")

    def _write(self, data: dict, name_hint: str = "") -> None:
        if not self.turn_dir:
            return
        filename = f"{self.file_seq:02d}_{name_hint}.json"
        self.file_seq += 1
        try:
            with open(self.turn_dir / filename, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except Exception as e:
            print(f"Warning: failed to write log {filename}: {e}")
