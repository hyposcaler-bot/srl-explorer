from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from openai.types.chat import ChatCompletionMessageToolCall
from openai.types.chat.chat_completion_message_tool_call import Function

from srl_explorer.agent import Agent, MAX_AGENT_ITERATIONS, MAX_TOOL_RESULT_SIZE
from srl_explorer.config import Config
from srl_explorer.tools.yang import YangIndex


def _make_config() -> Config:
    return Config(openai_api_key="sk-test", prometheus_url="http://localhost:9090")


def _make_agent(**kwargs) -> Agent:
    agent = Agent(_make_config(), YangIndex([]), **kwargs)
    return agent


def _mock_response(content: str | None, finish_reason: str = "stop", tool_calls=None):
    """Build a mock ChatCompletion response."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls

    choice = MagicMock()
    choice.message = msg
    choice.finish_reason = finish_reason

    usage = MagicMock()
    usage.prompt_tokens = 10
    usage.completion_tokens = 5
    usage.total_tokens = 15

    response = MagicMock()
    response.choices = [choice]
    response.usage = usage
    return response


def _mock_tool_call(tool_id: str, name: str, arguments: dict):
    """Build a mock tool call object."""
    return ChatCompletionMessageToolCall(
        id=tool_id,
        type="function",
        function=Function(name=name, arguments=json.dumps(arguments)),
    )


@pytest.mark.asyncio
async def test_simple_response():
    """Agent returns content when LLM responds with finish_reason='stop'."""
    agent = _make_agent()
    agent.client.chat.completions.create = AsyncMock(
        return_value=_mock_response("Hello, world!")
    )

    result = await agent.chat("hi")
    assert result == "Hello, world!"


@pytest.mark.asyncio
async def test_tool_dispatch():
    """Agent dispatches tool calls and passes correct arguments to gnmic_get."""
    tc = _mock_tool_call("call_1", "gnmic_get", {
        "target": "leaf1",
        "path": "/system/name",
    })
    tool_response = _mock_response(None, finish_reason="tool_calls", tool_calls=[tc])
    final_response = _mock_response("The hostname is leaf1.")

    agent = _make_agent()
    agent.client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, final_response]
    )

    with patch("srl_explorer.agent.gnmic_get", new_callable=AsyncMock) as mock_gnmic:
        mock_gnmic.return_value = {"name": "leaf1"}
        result = await agent.chat("get hostname of leaf1")

    mock_gnmic.assert_called_once_with(
        agent.config,
        target="leaf1",
        path="/system/name",
        data_type="ALL",
    )
    assert result == "The hostname is leaf1."


@pytest.mark.asyncio
async def test_tool_result_truncation():
    """Large tool results are truncated before being added to message history."""
    tc = _mock_tool_call("call_1", "get_current_time", {})
    tool_response = _mock_response(None, finish_reason="tool_calls", tool_calls=[tc])
    final_response = _mock_response("Done.")

    agent = _make_agent()
    agent.client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, final_response]
    )

    # Make get_current_time return a huge result
    huge_result = {"data": "x" * (MAX_TOOL_RESULT_SIZE + 1000)}
    with patch.object(agent, "_execute_tool", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = huge_result
        await agent.chat("what time is it")

    # Find the tool message in history
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert tool_msgs[0]["content"].endswith("... [truncated, result too large]")
    assert len(tool_msgs[0]["content"]) < len(json.dumps(huge_result))


@pytest.mark.asyncio
async def test_max_iterations_exceeded():
    """Agent raises RuntimeError after exceeding MAX_AGENT_ITERATIONS."""
    tc = _mock_tool_call("call_1", "get_current_time", {})
    # Always return a tool call, never finish
    looping_response = _mock_response(None, finish_reason="tool_calls", tool_calls=[tc])

    agent = _make_agent()
    agent.client.chat.completions.create = AsyncMock(return_value=looping_response)

    with patch.object(agent, "_execute_tool", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"utc_iso": "2026-01-01T00:00:00Z", "epoch": 0}
        with pytest.raises(RuntimeError, match=str(MAX_AGENT_ITERATIONS)):
            await agent.chat("loop forever")


@pytest.mark.asyncio
async def test_reasoning_extraction():
    """Reasoning tags are extracted, callback fires, and tags are stripped from history."""
    reasoning_content = "<reasoning>I need to check BGP state</reasoning>"
    tc = _mock_tool_call("call_1", "get_current_time", {})
    first_response = _mock_response(
        reasoning_content, finish_reason="tool_calls", tool_calls=[tc]
    )
    final_response = _mock_response("BGP is up.")

    reasoning_captured = []
    agent = _make_agent(on_reasoning=lambda text: reasoning_captured.append(text))
    agent.client.chat.completions.create = AsyncMock(
        side_effect=[first_response, final_response]
    )

    with patch.object(agent, "_execute_tool", new_callable=AsyncMock) as mock_exec:
        mock_exec.return_value = {"utc_iso": "2026-01-01T00:00:00Z", "epoch": 0}
        result = await agent.chat("show bgp")

    # Callback fired with extracted reasoning
    assert reasoning_captured == ["I need to check BGP state"]

    # Reasoning tags stripped from assistant messages in history
    assistant_msgs = [m for m in agent.messages if m.get("role") == "assistant"]
    for msg in assistant_msgs:
        if msg["content"]:
            assert "<reasoning>" not in msg["content"]

    assert result == "BGP is up."


@pytest.mark.asyncio
async def test_malformed_tool_arguments():
    """Malformed JSON in tool arguments produces a tool error instead of crashing."""
    bad_tc = ChatCompletionMessageToolCall(
        id="call_bad",
        type="function",
        function=Function(name="gnmic_get", arguments="{bad json"),
    )
    tool_response = _mock_response(None, finish_reason="tool_calls", tool_calls=[bad_tc])
    final_response = _mock_response("ok")

    agent = _make_agent()
    agent.client.chat.completions.create = AsyncMock(
        side_effect=[tool_response, final_response]
    )

    result = await agent.chat("do something")

    # A tool error message should be in the history
    tool_msgs = [m for m in agent.messages if m.get("role") == "tool"]
    assert len(tool_msgs) == 1
    assert "error" in tool_msgs[0]["content"]

    assert result == "ok"


@pytest.mark.asyncio
async def test_run_tool_call_success():
    """_run_tool_call returns a tool message with the JSON-serialized result."""
    agent = _make_agent()
    agent._execute_tool = AsyncMock(return_value={"status": "ok"})

    tc = _mock_tool_call("call_1", "gnmic_get", {"target": "leaf1", "path": "/system/name"})
    msg = await agent._run_tool_call(tc)

    assert msg["role"] == "tool"
    assert msg["tool_call_id"] == "call_1"
    assert json.loads(msg["content"]) == {"status": "ok"}


@pytest.mark.asyncio
async def test_run_tool_call_error():
    """_run_tool_call returns an error tool message when _execute_tool raises."""
    agent = _make_agent()
    agent._execute_tool = AsyncMock(side_effect=RuntimeError("connection refused"))

    tc = _mock_tool_call("call_1", "gnmic_get", {"target": "leaf1", "path": "/x"})
    msg = await agent._run_tool_call(tc)

    assert msg["role"] == "tool"
    parsed = json.loads(msg["content"])
    assert "connection refused" in parsed["error"]


@pytest.mark.asyncio
async def test_run_tool_call_truncation():
    """_run_tool_call truncates results larger than MAX_TOOL_RESULT_SIZE."""
    agent = _make_agent()
    huge = {"data": "x" * (MAX_TOOL_RESULT_SIZE + 1000)}
    agent._execute_tool = AsyncMock(return_value=huge)

    tc = _mock_tool_call("call_1", "get_current_time", {})
    msg = await agent._run_tool_call(tc)

    assert msg["content"].endswith("... [truncated, result too large]")
    assert len(msg["content"]) < len(json.dumps(huge))


@pytest.mark.asyncio
async def test_run_tool_call_callbacks():
    """on_tool_call and on_tool_result callbacks fire with correct arguments."""
    tool_calls_log: list[tuple] = []
    tool_results_log: list[tuple] = []

    agent = _make_agent(
        on_tool_call=lambda name, args: tool_calls_log.append((name, args)),
        on_tool_result=lambda name, result: tool_results_log.append((name, result)),
    )
    agent._execute_tool = AsyncMock(return_value={"val": 1})

    tc = _mock_tool_call("call_1", "gnmic_get", {"target": "leaf1", "path": "/x"})
    await agent._run_tool_call(tc)

    assert len(tool_calls_log) == 1
    assert tool_calls_log[0] == ("gnmic_get", {"target": "leaf1", "path": "/x"})

    assert len(tool_results_log) == 1
    assert tool_results_log[0][0] == "gnmic_get"
    assert json.loads(tool_results_log[0][1]) == {"val": 1}


@pytest.mark.asyncio
async def test_run_tool_call_malformed_args():
    """Malformed JSON args produce an error tool message; on_tool_call is NOT called."""
    tool_calls_log: list[tuple] = []
    agent = _make_agent(
        on_tool_call=lambda name, args: tool_calls_log.append((name, args)),
    )

    bad_tc = ChatCompletionMessageToolCall(
        id="call_bad",
        type="function",
        function=Function(name="gnmic_get", arguments="{bad json"),
    )
    msg = await agent._run_tool_call(bad_tc)

    assert msg["role"] == "tool"
    assert "error" in msg["content"]
    assert len(tool_calls_log) == 0


def test_extract_reasoning_with_tags():
    """Reasoning tags are stripped and the callback fires."""
    captured: list[str] = []
    agent = _make_agent(on_reasoning=lambda t: captured.append(t))

    result = agent._extract_reasoning(
        "<reasoning>Think carefully</reasoning>The answer is 42."
    )

    assert captured == ["Think carefully"]
    assert result == "The answer is 42."
    assert "<reasoning>" not in result


def test_extract_reasoning_only_tags():
    """Content that is only a reasoning block returns None."""
    agent = _make_agent()
    result = agent._extract_reasoning("<reasoning>Just thinking</reasoning>")
    assert result is None


def test_extract_reasoning_no_tags():
    """Plain content is returned unchanged; on_reasoning is not called."""
    captured: list[str] = []
    agent = _make_agent(on_reasoning=lambda t: captured.append(t))

    result = agent._extract_reasoning("plain text")

    assert result == "plain text"
    assert len(captured) == 0


def test_extract_reasoning_none_input():
    """None input returns None."""
    agent = _make_agent()
    assert agent._extract_reasoning(None) is None


def test_build_assistant_message_with_tools():
    """Message includes tool_calls list with correct structure."""
    agent = _make_agent()
    tc = _mock_tool_call("call_1", "gnmic_get", {"target": "leaf1", "path": "/x"})

    msg = agent._build_assistant_message("thinking...", [tc])

    assert msg["role"] == "assistant"
    assert msg["content"] == "thinking..."
    assert len(msg["tool_calls"]) == 1
    assert msg["tool_calls"][0]["id"] == "call_1"
    assert msg["tool_calls"][0]["type"] == "function"
    assert msg["tool_calls"][0]["function"]["name"] == "gnmic_get"


def test_build_assistant_message_without_tools():
    """Message without tool calls has no tool_calls key."""
    agent = _make_agent()
    msg = agent._build_assistant_message("done", [])

    assert msg["role"] == "assistant"
    assert msg["content"] == "done"
    assert "tool_calls" not in msg


@pytest.mark.asyncio
async def test_execute_tool_unknown():
    """_execute_tool raises ValueError for an unknown tool name."""
    agent = _make_agent()
    with pytest.raises(ValueError, match="Unknown tool"):
        await agent._execute_tool("nonexistent", {})


@pytest.mark.asyncio
async def test_execute_tool_prometheus_instant_vs_range():
    """prometheus_query dispatches instant vs range based on start/end args."""
    agent = _make_agent()

    with patch("srl_explorer.agent.prometheus_query", new_callable=AsyncMock) as mock_instant:
        mock_instant.return_value = {"result": []}
        await agent._execute_tool("prometheus_query", {"query": "up"})
        mock_instant.assert_called_once()

    with patch("srl_explorer.agent.prometheus_query_range", new_callable=AsyncMock) as mock_range:
        mock_range.return_value = {"result": []}
        await agent._execute_tool(
            "prometheus_query",
            {"query": "up", "start": "2026-01-01T00:00:00Z", "end": "2026-01-01T01:00:00Z"},
        )
        mock_range.assert_called_once()
