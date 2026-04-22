from __future__ import annotations

import json
from typing import Any, Dict, List

from omni_agent.agents.streaming_agent import StreamingAgent
from omni_agent.skills import SkillResult


class FakeVLLMClient:
    async def chat_completion(self, *args, **kwargs):
        raise AssertionError("fast-path request should not call the model")


class FakeBashSkill:
    async def execute(self, **kwargs):
        return SkillResult(
            success=False,
            content="total 8\n-rw-r--r--  1 user  staff  12 Apr 16 15:10 demo.txt\n",
        )


class FakeWeatherSkill:
    async def execute(self, **kwargs):
        return SkillResult(
            success=False,
            error="Please provide either city or both lat and lon.",
        )


class FakeSearchSkill:
    async def execute(self, **kwargs):
        return SkillResult(
            success=True,
            content="Shanghai today: 24C to 31C, cloudy, light wind.",
        )


class FakeComputerSkill:
    async def execute(self, **kwargs):
        action = kwargs.get("action")
        if action == "navigate":
            return SkillResult(success=True, content=f"Navigated to URL: {kwargs.get('url')}")
        return SkillResult(success=True, content="Screenshot taken successfully")


class FakeSkillManager:
    def __init__(self, skills: Dict[str, Any] | None = None) -> None:
        self.skills = skills or {"bash": FakeBashSkill()}

    def get_anthropic_tools(self) -> List[Dict[str, Any]]:
        tools = []
        for tool_name in self.skills:
            tools.append({
                "name": tool_name,
                "description": f"{tool_name} tool",
                "input_schema": {"type": "object", "properties": {}},
            })
        return tools

    def resolve_skill_name_for_tool(self, tool_name: str) -> str:
        return {
            "bash": "terminal",
            "weather": "weather",
            "advanced_web_search": "web-search",
            "web_search": "web-search",
        }.get(tool_name, tool_name)

    def build_skill_index(self, tool_names: List[str]) -> List[Dict[str, str]]:
        items = []
        for tool_name in tool_names:
            items.append({
                "name": self.resolve_skill_name_for_tool(tool_name),
                "tool_name": tool_name,
                "description": f"{tool_name} enabled",
            })
        return items

    def get_skill_instructions(self, skill_name: str) -> str:
        return f"instructions for {skill_name}"


class SilentAfterToolVLLMClient:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.final_messages: List[Dict[str, Any]] = []

    async def chat_completion(self, *args, **kwargs):
        if kwargs.get("stream"):
            self.stream_calls += 1

            async def _generator():
                if self.stream_calls == 1:
                    yield {
                        "choices": [{
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "computer",
                                        "arguments": json.dumps({
                                            "action": "navigate",
                                            "url": "http://10.25.35.73:8001/skill.md",
                                        }, ensure_ascii=False),
                                    },
                                }]
                            }
                        }]
                    }
                    return

                yield {"choices": [{"delta": {}}]}

            return _generator()

        self.final_messages = kwargs.get("messages") or []
        return {
            "choices": [{
                "message": {
                    "content": "我已经打开了页面，并准备继续按页面里的说明操作游戏。"
                }
            }]
        }


class RecoveryAfterToolFailureVLLMClient:
    def __init__(self) -> None:
        self.stream_calls = 0

    async def chat_completion(self, *args, **kwargs):
        if kwargs.get("stream"):
            self.stream_calls += 1

            async def _generator():
                if self.stream_calls == 1:
                    yield {
                        "choices": [{
                            "delta": {
                                "tool_calls": [{
                                    "index": 0,
                                    "id": "call_1",
                                    "function": {
                                        "name": "computer",
                                        "arguments": json.dumps({
                                            "action": "navigate",
                                            "url": "http://10.25.35.73:8001/skill.md",
                                        }, ensure_ascii=False),
                                    },
                                }]
                            }
                        }]
                    }
                    return
                raise RuntimeError("Client error 400 Bad Request")

            return _generator()

        raise RuntimeError("Client error 400 Bad Request")


class FailingFinalSynthesisVLLMClient:
    async def chat_completion(self, *args, **kwargs):
        raise RuntimeError("HTTPStatusError 400 during final synthesis")


class RecordingFinalSynthesisVLLMClient:
    def __init__(self) -> None:
        self.calls: List[List[Dict[str, Any]]] = []

    async def chat_completion(self, *args, **kwargs):
        self.calls.append(kwargs.get("messages") or [])
        return {
            "choices": [{
                "message": {
                    "content": "这里是整理后的最终总结。"
                }
            }]
        }


def _decode_events(chunks: List[str]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for chunk in chunks:
        if not chunk.startswith("data: "):
            continue
        events.append(json.loads(chunk[6:].strip()))
    return events


def test_tool_inventory_request_bypasses_compaction_and_model() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    async def forbidden_compaction(**kwargs):
        raise AssertionError("tool inventory request should bypass compaction")
        yield  # pragma: no cover

    agent._maybe_compact_conversation = forbidden_compaction  # type: ignore[assignment]

    async def _collect():
        chat_sessions = {"s1": [{"role": "user", "content": "你有什么skill"}]}
        events = []
        async for chunk in agent._native_tool_stream(
            session_id="s1",
            chat_sessions=chat_sessions,
            permission_mode="ask",
            permission_confirmed=False,
            context="",
            tool_context="workspace",
            enabled_skills=["terminal", "weather"],
            request_context={},
        ):
            events.append(chunk)
        return events

    import asyncio

    payloads = _decode_events(asyncio.run(_collect()))
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert "当前启用的工具只有这些" in answer["delta"]
    assert "terminal (bash)" in answer["delta"]


def test_directory_listing_output_is_treated_as_success() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    async def _collect():
        conversation_history = [{"role": "user", "content": "目录下有什么"}]
        return await agent._maybe_handle_direct_local_shell_request(
            session_id="s2",
            conversation_history=conversation_history,
            user_message="目录下有什么",
            tool_context="workspace",
            permission_mode="ask",
            permission_confirmed=False,
            tools=[{"name": "bash"}],
        )

    import asyncio

    payloads = _decode_events(asyncio.run(_collect()) or [])
    task_complete = next(item for item in payloads if item.get("type") == "task_complete")
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert task_complete["success"] is True
    assert "我直接查看了本地目录" in answer["delta"]


def test_compacted_user_prompt_does_not_duplicate_plain_text_message_parts() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    content = agent._compose_user_message_content(
        "[Current user request]\nhi",
        [{"type": "text", "text": "hi"}],
    )

    assert content == [{"type": "text", "text": "[Current user request]\nhi"}]


def test_compacted_user_prompt_keeps_images_without_repeating_text_parts() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    content = agent._compose_user_message_content(
        "[Current user request]\n看这张图",
        [
            {"type": "text", "text": "看这张图"},
            {"type": "image", "data_url": "data:image/png;base64,abc"},
        ],
    )

    assert content == [
        {"type": "text", "text": "[Current user request]\n看这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]


def test_compaction_only_runs_after_threshold() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())
    agent._estimate_context_percent = lambda messages: 60  # type: ignore[assignment]

    async def forbidden_summary(**kwargs):
        raise AssertionError("compaction should not run under threshold")
        yield  # pragma: no cover

    agent._summarize_context_block = forbidden_summary  # type: ignore[assignment]

    async def _collect():
        chat_sessions = {
            "s3": [
                {"role": "user", "content": "first"},
                {"role": "assistant", "content": "reply"},
                {"role": "user", "content": "second"},
            ]
        }
        chunks = []
        async for chunk in agent._maybe_compact_conversation(
            session_id="s3",
            chat_sessions=chat_sessions,
            request_context={},
        ):
            chunks.append(chunk)
        return chunks

    import asyncio

    chunks = asyncio.run(_collect())
    assert chunks == []


def test_weather_fast_path_falls_back_to_search_when_location_missing() -> None:
    agent = StreamingAgent(
        FakeVLLMClient(),
        FakeSkillManager({
            "weather": FakeWeatherSkill(),
            "advanced_web_search": FakeSearchSkill(),
        }),
    )

    async def _collect():
        chat_sessions = {"s4": [{"role": "user", "content": "今天天气"}]}
        chunks = []
        async for chunk in agent._maybe_handle_direct_readonly_request(
            session_id="s4",
            chat_sessions=chat_sessions,
            conversation_history=chat_sessions["s4"],
            user_message="今天天气",
            tools=[
                {"name": "weather"},
                {"name": "advanced_web_search"},
            ],
            request_context={},
            model=None,
        ):
            chunks.append(chunk)
        return chunks

    import asyncio

    payloads = _decode_events(asyncio.run(_collect()))
    phase = next(item for item in payloads if item.get("phase") == "fast_path")
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    task_start = next(item for item in payloads if item.get("type") == "task_start")
    assert phase["transient"] is True
    assert task_start["skill"] == "advanced_web_search"
    assert "Shanghai today" in answer["delta"]


def test_inline_url_request_is_rewritten_into_explicit_browser_task() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    rewritten = agent._rewrite_followup_reference_request([
        {"role": "user", "content": "://10.25.35.73:8001/skill.md 新建一个房间"},
    ])

    assert rewritten[-1]["content"] == "打开这个地址 http://10.25.35.73:8001/skill.md，然后新建一个房间。"


def test_followup_reference_request_reuses_previous_url() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    rewritten = agent._rewrite_followup_reference_request([
        {"role": "user", "content": "://10.25.35.73:8001/skill.md 新建一个房间"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "玩一下地址里说的游戏"},
    ])

    assert rewritten[-1]["content"] == "打开上条消息里的地址 http://10.25.35.73:8001/skill.md，然后玩一下地址里说的游戏。"


def test_inline_url_followup_does_not_duplicate_previous_reference() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())

    rewritten = agent._rewrite_followup_reference_request([
        {"role": "user", "content": "://10.25.35.73:8001/skill.md 新建一个房间"},
        {"role": "assistant", "content": "好的"},
        {"role": "user", "content": "玩一下这个游戏 10.25.35.73:8001/skill.md"},
    ])

    assert rewritten[-1]["content"] == "打开这个地址 http://10.25.35.73:8001/skill.md，然后玩一下这个游戏。"


def test_prompt_context_ignores_stale_cache_and_keeps_recent_turns() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())
    agent.session_context_cache["s5"] = {
        "historical_summary": "old historical",
        "recent_summary": "stale recent",
        "historical_signature": "bad-old-historical",
        "recent_signature": "bad-old-recent",
        "recent_turn_count": 20,
    }

    conversation_history = [
        {"role": "user", "content": "://10.25.35.73:8001/skill.md 新建一个房间"},
        {"role": "assistant", "content": "好的，我来处理"},
        {"role": "user", "content": "玩一下地址里说的游戏"},
    ]

    prompt_context = agent._resolve_prompt_context(
        session_id="s5",
        conversation_history=conversation_history,
    )

    assert prompt_context["historical_summary"] == ""
    assert prompt_context["recent_summary"] == ""
    assert "://10.25.35.73:8001/skill.md 新建一个房间" in prompt_context["recent_turn_transcript"]
    assert "好的，我来处理" in prompt_context["recent_turn_transcript"]


def test_prompt_context_caps_verbatim_history_to_latest_ten_turns() -> None:
    agent = StreamingAgent(FakeVLLMClient(), FakeSkillManager())
    agent.session_context_cache["s7"] = {
        "recent_turn_count": 25,
    }

    conversation_history = []
    for idx in range(1, 13):
        conversation_history.append({"role": "user", "content": f"user turn {idx}"})
        conversation_history.append({"role": "assistant", "content": f"assistant turn {idx}"})
    conversation_history.append({"role": "user", "content": "current request"})

    prompt_context = agent._resolve_prompt_context(
        session_id="s7",
        conversation_history=conversation_history,
    )

    transcript = prompt_context["recent_turn_transcript"]
    assert "User: user turn 1\n" not in transcript
    assert "Assistant: assistant turn 1\n" not in transcript
    assert "User: user turn 2\n" not in transcript
    assert "Assistant: assistant turn 2\n" not in transcript
    assert "User: user turn 3\n" in transcript
    assert "Assistant: assistant turn 12" in transcript


def test_native_tool_stream_synthesizes_final_answer_after_silent_tool_step() -> None:
    agent = StreamingAgent(
        SilentAfterToolVLLMClient(),
        FakeSkillManager({"computer": FakeComputerSkill()}),
    )

    async def _collect():
        chat_sessions = {"s6": [{"role": "user", "content": "玩一下这个游戏 10.25.35.73:8001/skill.md"}]}
        events = []
        async for chunk in agent._native_tool_stream(
            session_id="s6",
            chat_sessions=chat_sessions,
            permission_mode="ask",
            permission_confirmed=False,
            context="",
            tool_context="workspace",
            enabled_skills=["computer-use"],
            request_context={},
        ):
            events.append(chunk)
        return chat_sessions, events

    import asyncio

    chat_sessions, payload_chunks = asyncio.run(_collect())
    payloads = _decode_events(payload_chunks)
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert answer["delta"] == "我已经打开了页面，并准备继续按页面里的说明操作游戏。"
    assert chat_sessions["s6"][-1]["content"] == "我已经打开了页面，并准备继续按页面里的说明操作游戏。"


def test_native_tool_stream_recovers_after_model_failure_with_tool_result_summary() -> None:
    agent = StreamingAgent(
        RecoveryAfterToolFailureVLLMClient(),
        FakeSkillManager({"computer": FakeComputerSkill()}),
    )

    async def _collect():
        chat_sessions = {"s8": [{"role": "user", "content": "打开这个页面然后继续"}]}
        events = []
        async for chunk in agent._native_tool_stream(
            session_id="s8",
            chat_sessions=chat_sessions,
            permission_mode="ask",
            permission_confirmed=False,
            context="",
            tool_context="workspace",
            enabled_skills=["computer-use"],
            request_context={},
        ):
            events.append(chunk)
        return chat_sessions, events

    import asyncio

    chat_sessions, payload_chunks = asyncio.run(_collect())
    payloads = _decode_events(payload_chunks)
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert "我已经尽量保住这次执行里拿到的结果了" in answer["delta"]
    assert "Navigated to URL" in answer["delta"]
    assert chat_sessions["s8"][-1]["content"] == answer["delta"]
    assert not any(item.get("error") for item in payloads)


def test_final_synthesis_uses_recovery_answer_when_model_keeps_failing() -> None:
    agent = StreamingAgent(
        FailingFinalSynthesisVLLMClient(),
        FakeSkillManager({"advanced_web_search": FakeSearchSkill()}),
    )

    async def _collect():
        chat_sessions = {"s9": []}
        conversation_history = [{"role": "user", "content": "今天热点新闻"}]
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "今天热点新闻"},
            {"role": "tool", "name": "advanced_web_search", "content": "新华社头条：今日有三条重要新闻。"},
        ]
        events = []
        async for chunk in agent._stream_final_answer_without_tools(
            session_id="s9",
            chat_sessions=chat_sessions,
            conversation_history=conversation_history,
            messages=messages,
            instruction="请基于工具结果给出最终总结。",
            model="MiniMax-M2",
        ):
            events.append(chunk)
        return chat_sessions, events

    import asyncio

    chat_sessions, payload_chunks = asyncio.run(_collect())
    payloads = _decode_events(payload_chunks)
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert "我已经尽量保住这次执行里拿到的结果了" in answer["delta"]
    assert "新华社头条" in answer["delta"]
    assert chat_sessions["s9"][-1]["content"] == answer["delta"]


def test_final_synthesis_uses_compact_prompt_instead_of_full_history() -> None:
    client = RecordingFinalSynthesisVLLMClient()
    agent = StreamingAgent(
        client,
        FakeSkillManager({"advanced_web_search": FakeSearchSkill()}),
    )

    async def _collect():
        chat_sessions = {"s10": []}
        conversation_history = [
            {"role": "user", "content": "之前的超长上下文"},
            {"role": "assistant", "content": "之前的超长回答"},
            {"role": "user", "content": "今天热点新闻"},
        ]
        messages = [
            {"role": "system", "content": "very long system prompt " * 200},
            {"role": "user", "content": "[Current user request]\n今天热点新闻\n\n大量压缩上下文 " * 100},
            {"role": "tool", "name": "advanced_web_search", "content": "新华社头条：今日有三条重要新闻。\n" + ("详情 " * 200)},
        ]
        events = []
        async for chunk in agent._stream_final_answer_without_tools(
            session_id="s10",
            chat_sessions=chat_sessions,
            conversation_history=conversation_history,
            messages=messages,
            instruction="请基于工具结果给出最终总结。",
            model="MiniMax-M2",
        ):
            events.append(chunk)
        return chat_sessions, events

    import asyncio

    chat_sessions, payload_chunks = asyncio.run(_collect())
    payloads = _decode_events(payload_chunks)
    answer = next(item for item in payloads if item.get("type") == "answer_delta")
    assert answer["delta"] == "这里是整理后的最终总结。"
    assert chat_sessions["s10"][-1]["content"] == answer["delta"]
    assert len(client.calls) == 1
    assert len(client.calls[0]) == 2
    assert client.calls[0][0]["role"] == "system"
    assert "[Original user request]\n今天热点新闻" in client.calls[0][1]["content"]
    assert "[Completed tool outputs]\n[advanced_web_search]" in client.calls[0][1]["content"]
    assert "very long system prompt" not in client.calls[0][1]["content"]
