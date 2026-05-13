import asyncio
import json
from pathlib import Path
from typing import Optional

from agents.generator_agent import GeneratorAgent, _parse_tool_arguments


class _DummySkillManager:
    def __init__(self, workspace: Path) -> None:
        self._workspace = workspace

    def get_current_workspace(self) -> str:
        return str(self._workspace)

    def resolve_skill_name_for_tool(self, tool_name: str) -> Optional[str]:
        if tool_name == "str_replace_editor":
            return "file_writer"
        return None

    async def execute_skill(self, *args, **kwargs):
        raise AssertionError("Harness file tools should execute inside GeneratorAgent")


class _ToolCallingVllm:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=2400, stream=True, model=None):
        self.calls += 1
        assert any(tool["name"] == "file-manager" for tool in tools)
        if self.calls == 1:
            args = json.dumps({
                "command": "create",
                "path": "index.html",
                "file_text": "<!doctype html><canvas id=\"game\"></canvas><script>window.__ok=true</script>",
            })

            async def first_stream():
                yield {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_1",
                                        "type": "function",
                                        "function": {"name": "file-manager", "arguments": args},
                                    }
                                ]
                            }
                        }
                    ]
                }

            return first_stream()

        payload = {
            "schema_version": "1.0",
            "task_id": "task_generator_tool",
            "round_id": 1,
            "mode": "initial",
            "changed_files": ["index.html"],
            "created_files": ["index.html"],
            "deleted_files": [],
            "summary": "Created playable HTML game shell.",
            "implementation_notes": [],
            "commands_to_run": [{"name": "syntax", "cmd": "python -m http.server 0", "reason": "smoke"}],
            "risk_points": [],
            "patch_envelope": {"operations": [{"path": "index.html"}], "changed_files": ["index.html"]},
            "needs_replan": False,
            "replan_reason": "",
        }

        async def second_stream():
            yield {"choices": [{"delta": {"content": json.dumps(payload)}}]}

        return second_stream()


class _MalformedThenValidToolCallingVllm:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=2400, stream=True, model=None):
        self.calls += 1
        if self.calls == 1:
            async def first_stream():
                yield {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_bad",
                                        "type": "function",
                                        "function": {
                                            "name": "file-manager",
                                            "arguments": '{"command":"create","path":"index.html","file_text":"unterminated}',
                                        },
                                    }
                                ]
                            }
                        }
                    ]
                }

            return first_stream()

        if self.calls == 2:
            serialized_messages = json.dumps(messages, ensure_ascii=False)
            assert "Harness rejected the previous file-manager tool call" in serialized_messages
            assert 'call_bad' not in serialized_messages
            args = json.dumps({
                "command": "create",
                "path": "index.html",
                "file_text": "<html><body>ok</body></html>",
            })

            async def second_stream():
                yield {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_good",
                                        "type": "function",
                                        "function": {"name": "file-manager", "arguments": args},
                                    }
                                ]
                            }
                        }
                    ]
                }

            return second_stream()

        payload = {
            "schema_version": "1.0",
            "task_id": "task_generator_tool",
            "round_id": 1,
            "mode": "initial",
            "changed_files": ["index.html"],
            "created_files": ["index.html"],
            "deleted_files": [],
            "summary": "Recovered after malformed tool arguments.",
            "implementation_notes": [],
            "commands_to_run": [],
            "risk_points": [],
            "patch_envelope": {"operations": [{"path": "index.html"}], "changed_files": ["index.html"]},
            "needs_replan": False,
            "replan_reason": "",
        }

        async def final_stream():
            yield {"choices": [{"delta": {"content": json.dumps(payload)}}]}

        return final_stream()


class _ProviderRejectsThenValidVllm:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=2400, stream=True, model=None):
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError(
                "Client error '400 Bad Request' for url 'https://example.test' invalid function arguments json string"
            )
        if self.calls == 2:
            serialized_messages = json.dumps(messages, ensure_ascii=False)
            assert "Harness rejected the previous response before tool execution" in serialized_messages
            args = json.dumps(
                {
                    "command": "create",
                    "path": "game.js",
                    "file_text": "window.__gameOk = true;",
                }
            )

            async def second_stream():
                yield {
                    "choices": [
                        {
                            "delta": {
                                "tool_calls": [
                                    {
                                        "index": 0,
                                        "id": "call_provider_retry",
                                        "type": "function",
                                        "function": {"name": "file-manager", "arguments": args},
                                    }
                                ]
                            }
                        }
                    ]
                }

            return second_stream()

        payload = {
            "schema_version": "1.0",
            "task_id": "task_generator_tool",
            "round_id": 1,
            "mode": "initial",
            "changed_files": ["game.js"],
            "created_files": ["game.js"],
            "deleted_files": [],
            "summary": "Recovered after provider-side invalid tool argument rejection.",
            "implementation_notes": [],
            "commands_to_run": [],
            "risk_points": [],
            "patch_envelope": {"operations": [{"path": "game.js"}], "changed_files": ["game.js"]},
            "needs_replan": False,
            "replan_reason": "",
        }

        async def final_stream():
            yield {"choices": [{"delta": {"content": json.dumps(payload)}}]}

        return final_stream()


def test_parse_tool_arguments_rejects_malformed_json() -> None:
    args, error = _parse_tool_arguments('{"path":"index.html","content":"unterminated}')

    assert args == {}
    assert error is not None
    assert "Malformed tool arguments" in error


def test_generator_resolves_tool_name_before_execution(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=None, skill_manager=_DummySkillManager(tmp_path))

    assert agent._resolve_skill_name("str_replace_editor") == "file_writer"
    assert agent._resolve_skill_name("filesystem") == "filesystem"


def test_generator_harness_file_tool_creates_allowed_file(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=_ToolCallingVllm(), skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["index.html"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["index.html"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }

    async def collect() -> None:
        async for _ in agent.generate("generator-session", generator_input, tools=[]):
            pass

    asyncio.run(collect())

    assert (tmp_path / "index.html").exists()
    assert "window.__ok" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert agent.last_patch_result["created_files"] == ["index.html"]


def test_generator_view_workspace_root_returns_directory_listing(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=None, skill_manager=_DummySkillManager(tmp_path))
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.js").write_text("console.log('ok')", encoding="utf-8")
    generator_input = {
        "plan_contract": {"allowed_files": ["index.html", "src/**"], "forbidden_files": []},
        "harness_constraints": {"allowed_write_paths": ["index.html", "src/**"], "forbidden_write_paths": []},
    }

    success, content = asyncio.run(agent._execute_harness_file_tool({"command": "view", "path": "."}, generator_input))

    assert success is True
    assert "Directory listing for .:" in content
    assert "- index.html" in content
    assert "- src/" in content



def test_generator_recovers_after_malformed_tool_arguments(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=_MalformedThenValidToolCallingVllm(), skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["index.html"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["index.html"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }

    async def collect() -> None:
        async for _ in agent.generate("generator-session", generator_input, tools=[]):
            pass

    asyncio.run(collect())

    assert (tmp_path / "index.html").exists()
    assert "ok" in (tmp_path / "index.html").read_text(encoding="utf-8")
    assert agent.last_patch_result["summary"] == "Recovered after malformed tool arguments."



def test_generator_recovers_after_provider_rejects_invalid_tool_args(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=_ProviderRejectsThenValidVllm(), skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["game.js"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["game.js"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }

    async def collect() -> None:
        async for _ in agent.generate("generator-session", generator_input, tools=[]):
            pass

    asyncio.run(collect())

    assert (tmp_path / "game.js").exists()
    assert "window.__gameOk" in (tmp_path / "game.js").read_text(encoding="utf-8")
    assert agent.last_patch_result["summary"] == "Recovered after provider-side invalid tool argument rejection."


def test_generator_preserves_model_patch_envelope_when_files_are_not_written_yet(tmp_path: Path) -> None:
    agent = GeneratorAgent(vllm_client=None, skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["index.html"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["index.html"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }
    raw_obj = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "changed_files": [],
        "created_files": ["index.html"],
        "deleted_files": [],
        "summary": "Prepared patch envelope only.",
        "implementation_notes": [],
        "commands_to_run": [],
        "risk_points": [],
        "patch_envelope": {
            "schema_version": "1.0",
            "task_id": "task_generator_tool",
            "round_id": 1,
            "patch_type": "file_replacement",
            "operations": [
                {
                    "op": "file_replacement",
                    "path": "index.html",
                    "content": "<html><body>ready</body></html>",
                }
            ],
            "changed_files": ["index.html"],
        },
        "needs_replan": False,
        "replan_reason": "",
    }

    patch_result = agent._build_patch_result({}, {}, generator_input, raw_obj)

    assert patch_result["created_files"] == ["index.html"]
    assert patch_result["patch_envelope"]["operations"][0]["content"] == "<html><body>ready</body></html>"
    assert patch_result["patch_envelope"]["changed_files"] == ["index.html"]


def test_generator_switches_to_patch_envelope_guidance_after_repeated_invalid_tool_calls(tmp_path: Path) -> None:
    class _RepeatedMalformedThenPatchOnlyVllm:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=2400, stream=True, model=None):
            self.calls += 1
            if self.calls in {1, 2}:
                async def malformed_stream():
                    yield {
                        "choices": [
                            {
                                "delta": {
                                    "tool_calls": [
                                        {
                                            "index": 0,
                                            "id": f"call_bad_{self.calls}",
                                            "type": "function",
                                            "function": {
                                                "name": "file-manager",
                                                "arguments": '{"command":"create","path":"game.js","file_text":"unterminated}',
                                            },
                                        }
                                    ]
                                }
                            }
                        ]
                    }

                return malformed_stream()

            serialized_messages = json.dumps(messages, ensure_ascii=False)
            assert "Do not call the file tool again for this file if JSON escaping keeps failing." in serialized_messages
            payload = {
                "schema_version": "1.0",
                "task_id": "task_generator_tool",
                "round_id": 1,
                "mode": "initial",
                "changed_files": [],
                "created_files": ["game.js"],
                "deleted_files": [],
                "summary": "Fell back to patch-only output after repeated tool argument failures.",
                "implementation_notes": [],
                "commands_to_run": [],
                "risk_points": [],
                "patch_envelope": {
                    "schema_version": "1.0",
                    "task_id": "task_generator_tool",
                    "round_id": 1,
                    "patch_type": "file_replacement",
                    "operations": [
                        {
                            "op": "file_replacement",
                            "path": "game.js",
                            "content": "window.__gameReady = true;",
                        }
                    ],
                    "changed_files": ["game.js"],
                },
                "needs_replan": False,
                "replan_reason": "",
            }

            async def final_stream():
                yield {"choices": [{"delta": {"content": json.dumps(payload)}}]}

            return final_stream()

    agent = GeneratorAgent(vllm_client=_RepeatedMalformedThenPatchOnlyVllm(), skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["game.js"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["game.js"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }

    async def collect() -> None:
        async for _ in agent.generate("generator-session", generator_input, tools=[]):
            pass

    import asyncio

    asyncio.run(collect())

    assert agent.last_patch_result["created_files"] == ["game.js"]
    assert agent.last_patch_result["patch_envelope"]["operations"][0]["content"] == "window.__gameReady = true;"


def test_generator_retries_when_model_returns_incomplete_json_patch_result(tmp_path: Path) -> None:
    class _IncompleteJsonThenCompleteVllm:
        def __init__(self) -> None:
            self.calls = 0

        async def chat_completion(self, *, messages, tools=None, temperature=0.1, max_tokens=2400, stream=True, model=None):
            self.calls += 1
            if self.calls == 1:
                partial = (
                    '{"schema_version":"1.0","task_id":"task_generator_tool","round_id":1,'
                    '"mode":"initial","changed_files":[],"created_files":["index.html"],'
                    '"deleted_files":[],"summary":"partial"'
                )

                async def partial_stream():
                    yield {"choices": [{"delta": {"content": partial}}]}

                return partial_stream()

            serialized_messages = json.dumps(messages, ensure_ascii=False)
            assert "The previous response was not a complete valid JSON PatchResult object." in serialized_messages
            payload = {
                "schema_version": "1.0",
                "task_id": "task_generator_tool",
                "round_id": 1,
                "mode": "initial",
                "changed_files": [],
                "created_files": ["index.html"],
                "deleted_files": [],
                "summary": "Recovered after incomplete JSON output.",
                "implementation_notes": [],
                "commands_to_run": [],
                "risk_points": [],
                "patch_envelope": {
                    "schema_version": "1.0",
                    "task_id": "task_generator_tool",
                    "round_id": 1,
                    "patch_type": "file_replacement",
                    "operations": [
                        {
                            "op": "file_replacement",
                            "path": "index.html",
                            "content": "<html><body>ok</body></html>",
                        }
                    ],
                    "changed_files": ["index.html"],
                },
                "needs_replan": False,
                "replan_reason": "",
            }

            async def final_stream():
                yield {"choices": [{"delta": {"content": json.dumps(payload)}}]}

            return final_stream()

    agent = GeneratorAgent(vllm_client=_IncompleteJsonThenCompleteVllm(), skill_manager=_DummySkillManager(tmp_path))
    generator_input = {
        "schema_version": "1.0",
        "task_id": "task_generator_tool",
        "round_id": 1,
        "mode": "initial",
        "workspace": str(tmp_path),
        "plan_contract": {
            "task_id": "task_generator_tool",
            "allowed_files": ["index.html"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [],
        },
        "harness_constraints": {
            "allowed_write_paths": ["index.html"],
            "forbidden_write_paths": [".env", ".harness/**", "package.json"],
        },
    }

    async def collect() -> None:
        async for _ in agent.generate("generator-session", generator_input, tools=[]):
            pass

    asyncio.run(collect())

    assert agent.last_patch_result["created_files"] == ["index.html"]
    assert agent.last_patch_result["summary"] == "Recovered after incomplete JSON output."
