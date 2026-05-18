from agents.planner_agent import _default_dev_server, _ensure_game_smoke_tests


def test_default_dev_server_prefers_static_server_for_standalone_html_output() -> None:
    result = _default_dev_server(["package.json", "index.html"], ["game.html"])

    assert result["enabled"] is True
    assert "http.server" in result["start_cmd"]
    assert result["url"] == "http://localhost:8080"


def test_default_dev_server_keeps_project_dev_server_for_source_changes() -> None:
    result = _default_dev_server(["package.json", "src/App.tsx"], ["src/components/Button.tsx"])

    assert result["enabled"] is True
    assert "npm run dev" in result["start_cmd"]


def test_game_requests_get_browser_smoke_tests_for_html_targets() -> None:
    smoke_tests = _ensure_game_smoke_tests("写个跑酷游戏", [], ["test.html"])

    assert smoke_tests
    assert smoke_tests[0]["target"] == "test.html"


def test_non_game_non_web_outputs_do_not_get_game_smoke_tests() -> None:
    smoke_tests = _ensure_game_smoke_tests("写个脚本", [], ["test.py"])

    assert smoke_tests == []
