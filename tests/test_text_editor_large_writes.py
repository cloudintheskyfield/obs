from __future__ import annotations

import asyncio
from pathlib import Path

from skills.text_editor import TextEditorSkill


class FakeVLLMClient:
    async def chat_completion(self, *args, **kwargs):
        raise AssertionError("not used")


class FakeSkillManager:
    def __init__(self) -> None:
        self.skills = {}

    def get_current_workspace(self) -> str:
        return "/tmp/workspace"


def test_text_editor_write_and_append_chunks_for_large_html(tmp_path: Path) -> None:
    skill = TextEditorSkill(work_dir=str(tmp_path))

    async def run() -> None:
        first = await skill.execute(
            command="write",
            path="index.html",
            file_text="<!doctype html>\n<html><body>\n",
        )
        assert first.success, first.error

        for index in range(8):
            chunk = f"<section data-i=\"{index}\">" + ("x" * 1200) + "</section>\n"
            result = await skill.execute(command="append", path="index.html", file_text=chunk)
            assert result.success, result.error

        last = await skill.execute(command="append", path="index.html", new_str="</body></html>\n")
        assert last.success, last.error

    asyncio.run(run())

    content = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert content.startswith("<!doctype html>")
    assert content.endswith("</body></html>\n")
    assert len(content) > 9000


def test_text_editor_tool_schema_advertises_write_append() -> None:
    skill = TextEditorSkill(work_dir="workspace")
    tool = skill.to_anthropic_tool()
    command_description = tool["input_schema"]["properties"]["command"]["description"]

    assert "write" in command_description
    assert "append" in command_description
    assert "large files" in command_description


def test_text_editor_rejects_compacted_placeholder_content(tmp_path: Path) -> None:
    skill = TextEditorSkill(work_dir=str(tmp_path))

    async def run() -> None:
        result = await skill.execute(
            command="write",
            path="game.js",
            file_text="<large file_text omitted from history; do not copy or execute this placeholder>",
        )
        assert not result.success
        assert "compacted-history placeholder" in (result.error or "")

    asyncio.run(run())
    assert not (tmp_path / "game.js").exists()
