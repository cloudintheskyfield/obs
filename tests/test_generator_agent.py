import asyncio
import json
from pathlib import Path
from typing import Optional

from omni_agent.agents.generator_agent import GeneratorAgent, _parse_tool_arguments


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
