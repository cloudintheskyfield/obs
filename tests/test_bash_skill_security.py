from __future__ import annotations

import asyncio
import sys
from pathlib import Path


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from omni_agent.skills.bash import BashSkill


def test_allows_nohup_for_local_service_startup() -> None:
    skill = BashSkill(work_dir="workspace")
    assert skill._is_safe_command(
        'nohup python3 /Users/wangshuang/PycharmProjects/gomoku/main.py > /tmp/gomoku.log 2>&1 &'
    )


def test_allows_lsof_for_port_diagnostics() -> None:
    skill = BashSkill(work_dir="workspace")
    assert skill._is_safe_command('lsof -i :8008 2>/dev/null || echo "Port 8008 is free"')


def test_allows_pkill_without_force_kill() -> None:
    skill = BashSkill(work_dir="workspace")
    assert skill._is_safe_command('pkill -f "python3 main.py" 2>/dev/null')


def test_blocks_forceful_pkill() -> None:
    skill = BashSkill(work_dir="workspace")
    assert not skill._is_safe_command("pkill -9 python3")


def test_allows_env_wrapped_python_command() -> None:
    skill = BashSkill(work_dir="workspace")
    assert skill._is_safe_command('env PYTHONUNBUFFERED=1 python3 -m http.server 8123')


def test_tool_schema_exposes_background_parameter() -> None:
    skill = BashSkill(work_dir="workspace")
    tool = skill.to_anthropic_tool()
    assert "background" in tool["input_schema"]["properties"]


def test_rejects_compacted_history_placeholder_command() -> None:
    skill = BashSkill(work_dir="workspace")
    result = asyncio.run(skill.execute(command="[omitted 12000 chars]", timeout=1))

    assert not result.success
    assert "compacted-history placeholder" in (result.error or "")
