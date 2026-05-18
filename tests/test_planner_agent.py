from pathlib import Path

from agents.planner_agent import _default_plan_contract, _normalize_plan_contract


def test_planner_filters_browser_description_out_of_test_commands() -> None:
    contract = _normalize_plan_contract(
        {
            "task_id": "task_html_game",
            "goal": "生成一个可以直接打开的 index.html 小游戏",
            "allowed_files": ["index.html"],
            "forbidden_files": [".env", ".harness/**", "package.json"],
            "test_commands": [
                {
                    "name": "open_page",
                    "cmd": "在浏览器中直接打开index.html文件",
                    "timeout_sec": 30,
                    "required": True,
                }
            ],
            "smoke_tests": [],
        },
        "生成一个可以直接打开的 index.html 小游戏",
        [],
    )

    command_texts = [command["cmd"] for command in contract["test_commands"]]
    assert "在浏览器中直接打开index.html文件" not in command_texts
    assert any(
        command.startswith("python -c ") and "index.html" in command
        for command in command_texts
    )
    assert contract["smoke_tests"][0]["type"] == "browser"
    assert contract["smoke_tests"][0]["target"] == "index.html"


def test_planner_keeps_real_shell_commands_and_adds_output_check() -> None:
    contract = _normalize_plan_contract(
        {
            "goal": "创建 index.html",
            "allowed_files": ["index.html"],
            "test_commands": [
                {"name": "syntax", "cmd": "node --check game.js", "timeout_sec": 30}
            ],
        },
        "创建 index.html",
        [],
    )

    command_texts = [command["cmd"] for command in contract["test_commands"]]
    assert command_texts[0].startswith("python -c ")
    assert "node --check game.js" in command_texts


def test_planner_derives_fallback_steps_from_current_contract() -> None:
    contract = _normalize_plan_contract(
        {
            "goal": "创建 index.html 忍者小游戏",
            "allowed_files": ["index.html"],
            "required_files_to_inspect": [],
            "implementation_steps": [],
            "test_commands": [],
        },
        "创建 index.html 忍者小游戏",
        [],
    )

    combined_steps = "\n".join(
        f"{step['title']} {step['description']} {step['expected_output']}"
        for step in contract["implementation_steps"]
    )
    assert "index.html" in combined_steps
    assert "忍者小游戏" in combined_steps
    assert "现有项目结构" not in combined_steps


def test_planner_has_no_static_default_implementation_steps_constant() -> None:
    source = Path("src/agents/planner_agent.py").read_text(encoding="utf-8")

    assert "_DEFAULT_IMPLEMENTATION_STEPS" not in source


def test_planner_adds_interactive_smoke_tests_for_game_requests() -> None:
    contract = _normalize_plan_contract(
        {
            "goal": "创建一个忍者跑酷小游戏",
            "allowed_files": ["index.html"],
            "smoke_tests": [
                {
                    "id": "page_load",
                    "type": "browser",
                    "action": "goto",
                    "target": "index.html",
                    "expect": {"page_loaded": True},
                    "timeout_sec": 15,
                    "required": True,
                }
            ],
        },
        "创建一个忍者跑酷小游戏",
        [],
    )

    actions = {item["action"] for item in contract["smoke_tests"]}

    assert "evaluate" in actions
    assert "click" in actions
    assert "keyboard" in actions


def test_planner_default_contract_for_empty_game_workspace_is_runnable() -> None:
    contract = _default_plan_contract(
        "生成一个第一人称3D游戏，玩家可以用鼠标控制视角，用WASD移动",
        [],
    )

    assert "index.html" in contract["allowed_files"]
    assert contract["dev_server"]["enabled"] is True
    assert "http.server" in contract["dev_server"]["start_cmd"]
    assert any("index.html" in command["cmd"] for command in contract["test_commands"])
    assert {item["action"] for item in contract["smoke_tests"]} >= {
        "goto",
        "evaluate",
        "click",
        "keyboard",
    }


def test_planner_prunes_stale_generated_file_checks_outside_allowed_files() -> None:
    contract = _normalize_plan_contract(
        {
            "goal": "Create a first person 3D game",
            "allowed_files": ["first_person_game.html"],
            "test_commands": [
                {
                    "name": "verify_generated_files",
                    "cmd": "python -c \"from pathlib import Path; files=['index.html']; missing=[p for p in files if not Path(p).is_file() or Path(p).stat().st_size == 0]; assert not missing, 'missing or empty generated files: '+', '.join(missing)\"",
                    "timeout_sec": 30,
                    "required": True,
                }
            ],
        },
        "Create a first person 3D game",
        [],
    )

    command_texts = [command["cmd"] for command in contract["test_commands"]]
    assert any("first_person_game.html" in command for command in command_texts)
    assert not any("index.html" in command for command in command_texts)


def test_planner_prunes_stale_checks_when_allowed_files_are_globs() -> None:
    contract = _normalize_plan_contract(
        {
            "goal": "Create a 3D sokoban game",
            "allowed_files": ["*.html", "*.js", "*.css"],
            "test_commands": [
                {
                    "name": "verify_generated_files",
                    "cmd": "python -c \"from pathlib import Path; files=['index.html']; missing=[p for p in files if not Path(p).is_file() or Path(p).stat().st_size == 0]; assert not missing, 'missing or empty generated files: '+', '.join(missing)\"",
                    "timeout_sec": 30,
                    "required": True,
                }
            ],
            "dev_server": {
                "enabled": True,
                "start_cmd": "python3 -m http.server 8080",
                "url": "http://localhost:8080/sokoban3d.html",
                "ready_patterns": ["Serving HTTP"],
                "timeout_sec": 60,
            },
            "smoke_tests": [
                {
                    "id": "page_load",
                    "type": "browser",
                    "action": "goto",
                    "target": "sokoban3d.html",
                    "expect": {"page_loaded": True},
                    "timeout_sec": 15,
                    "required": True,
                }
            ],
        },
        "Create a 3D sokoban game",
        [],
    )

    assert not any("index.html" in command["cmd"] for command in contract["test_commands"])
