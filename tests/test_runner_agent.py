from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from agents.harness_engine import HarnessEngine
from agents.runner_agent import (
    RunnerAgent,
    _fallback_run_report,
    _infer_browser_key,
    _normalize_browser_key,
    _normalize_run_report,
)


def test_normalize_run_report_keeps_spec_shaped_artifacts_object() -> None:
    harness = HarnessEngine()
    report = _normalize_run_report(
        {
            "status": "TIMEOUT",
            "artifacts": {
                "run_dir": ".harness/runs/run_001",
                "screenshots": ["a.png"],
                "traces": ["trace.zip"],
                "logs": ["runner.log"],
                "browser_console": "console.log('ready')",
            },
        },
        {
            "task_id": "task_runtime_001",
            "round_id": 1,
            "run_dir": ".harness/runs/run_001",
            "plan_contract": {"task_id": "task_runtime_001"},
        },
        harness,
    )

    assert report["status"] == "TIMEOUT"
    assert report["artifacts"]["run_dir"] == ".harness/runs/run_001"
    assert report["artifacts"]["screenshots"] == ["a.png"]
    assert report["artifacts"]["traces"] == ["trace.zip"]
    assert report["artifacts"]["logs"] == ["runner.log"]
    assert report["artifacts"]["browser_console"] == "console.log('ready')"


def test_fallback_run_report_uses_infra_error_and_object_artifacts() -> None:
    harness = HarnessEngine()
    report = _fallback_run_report(
        {
            "task_id": "task_runtime_001",
            "round_id": 2,
            "run_dir": ".harness/runs/run_002",
            "plan_contract": {"task_id": "task_runtime_001"},
        },
        "runner crashed",
        harness,
    )

    assert report["status"] == "INFRA_ERROR"
    assert report["artifacts"]["run_dir"] == ".harness/runs/run_002"
    assert report["artifacts"]["screenshots"] == []
    assert report["artifacts"]["logs"] == []


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def test_runner_normalizes_space_key_without_stripping_it_away() -> None:
    assert _normalize_browser_key(" ") == "Space"
    assert _normalize_browser_key("space") == "Space"
    assert _infer_browser_key({"id": "jump_action", "action": "keyboard"}) == "Space"


def test_runner_executes_harness_provided_commands_and_writes_logs(
    tmp_path: Path,
) -> None:
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_e2e",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_e2e"},
        "patch_result": {"changed_files": []},
        "test_commands": [
            {
                "name": "python_ok",
                "cmd": "python -c \"print('harness-e2e-ok')\"",
                "timeout_sec": 30,
                "required": True,
            }
        ],
        "dev_server": {},
        "smoke_tests": [],
        "runner_limits": {},
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["commands"][0]["status"] == "PASSED"
    assert "harness-e2e-ok" in report["commands"][0]["stdout_tail"]
    assert (tmp_path / report["commands"][0]["log"]).exists()


def test_runner_starts_dev_server_and_executes_smoke_tests(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        "<html><body>runner ok</body></html>", encoding="utf-8"
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_browser",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_browser"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": f"http://127.0.0.1:{port}",
                "expect": {"page_loaded": True, "contains": "runner ok"},
                "timeout_sec": 10,
                "required": True,
            }
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["dev_server"]["ready"] is True
    assert report["dev_server"]["status"] == "PASSED"
    assert report["browser_tests"][0]["status"] == "PASSED"
    assert report["browser_tests"][0]["passed"] is True
    assert report["cleanup"]["dev_server_stopped"] is True
    assert (tmp_path / report["dev_server"]["log"]).exists()


def test_runner_supports_deterministic_evaluate_smoke_test(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        "<html><body><h1>runner ok</h1></body></html>", encoding="utf-8"
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_evaluate",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_evaluate"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "content_visible",
                "type": "browser",
                "action": "evaluate",
                "target": "document.body.innerText.length > 0",
                "expect": {"result": True},
                "timeout_sec": 10,
                "required": True,
            }
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][0]["status"] == "PASSED"
    assert report["browser_tests"][0]["evaluation_result"] is True


def test_runner_evaluate_accepts_selector_targets(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        """<!doctype html>
<html>
  <body>
    <h1>OBS REAL E2E PASS</h1>
    <button id="start" onclick="document.getElementById('status').textContent='clicked'">Start</button>
    <p id="status">ready</p>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_selector_evaluate",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_selector_evaluate"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "index.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "body_text",
                "type": "browser",
                "action": "evaluate",
                "target": "body",
                "expect": {"contains": "OBS REAL E2E PASS"},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "click_button",
                "type": "browser",
                "action": "click",
                "selector_candidates": ["#start"],
                "expect": {},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "status_text",
                "type": "browser",
                "action": "evaluate",
                "selector_candidates": ["#status"],
                "expect": {"contains": "clicked"},
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert [item["status"] for item in report["browser_tests"]] == [
        "PASSED",
        "PASSED",
        "PASSED",
        "PASSED",
    ]
    assert report["browser_tests"][1]["evaluation_result"].find(
        "OBS REAL E2E PASS"
    ) >= 0
    assert report["browser_tests"][3]["evaluation_result"] == "clicked"


def test_runner_resolves_glob_smoke_target_against_generated_html(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        "<!doctype html><html><body><canvas id='game'></canvas><script>requestAnimationFrame(()=>{})</script></body></html>",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_glob_target",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_glob_target"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}/game.html",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "*.html",
                "expect": {"page_loaded": True, "no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            }
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][0]["target"] == f"http://127.0.0.1:{port}/game.html"
    assert report["browser_tests"][0]["status"] == "PASSED"


def test_runner_resolves_missing_index_target_to_existing_html(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "dino_jump.html").write_text(
        "<!doctype html><html><body><canvas id='game'></canvas></body></html>",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_missing_index",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_missing_index"},
        "patch_result": {"changed_files": ["dino_jump.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "index.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            }
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][0]["target"] == f"http://127.0.0.1:{port}/dino_jump.html"


def test_runner_normalizes_evaluate_key_and_visual_change_smoke_tests(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        """<!doctype html>
<html>
  <body>
    <canvas id="game" width="220" height="120"></canvas>
    <script>
      const canvas = document.getElementById('game');
      const ctx = canvas.getContext('2d');
      let x = 10;
      function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#238';
        ctx.fillRect(x, 30, 40, 40);
        x = (x + 3) % canvas.width;
        requestAnimationFrame(draw);
      }
      document.addEventListener('keydown', (event) => {
        if (event.code === 'Space') x += 30;
      });
      draw();
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_visual_change",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_visual_change"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "game.html",
                "expect": {"page_loaded": True, "no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "space_key_from_evaluate",
                "type": "browser",
                "action": "evaluate",
                "key": "Space",
                "expect": {"game_responsive": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "visual_change_from_evaluate",
                "type": "browser",
                "action": "evaluate",
                "duration_ms": 800,
                "expect": {"no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert [item["action"] for item in report["browser_tests"]] == [
        "goto",
        "keyboard",
        "visual_change",
    ]
    assert report["browser_tests"][2]["evaluation_result"] is True


def test_runner_skips_hidden_click_candidates_and_ignores_optional_failure_for_status(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        """<!doctype html>
<html>
  <body>
    <button style="display:none">hidden</button>
    <canvas id="game" width="160" height="90"></canvas>
    <script>
      const ctx = document.getElementById('game').getContext('2d');
      ctx.fillStyle = '#283'; ctx.fillRect(10, 10, 40, 40);
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_hidden_click",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_hidden_click"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "game.html",
                "expect": {"page_loaded": True, "no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "optional_click",
                "type": "browser",
                "action": "click",
                "selector_candidates": ["button", "canvas"],
                "expect": {"no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": False,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["status"] == "PASSED"
    assert any("canvas" in item for item in report["browser_tests"][1]["evidence"])


def test_runner_click_visual_change_uses_pre_click_screenshot(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        """<!doctype html>
<html>
  <body>
    <button id="start">Start</button>
    <canvas id="game" width="160" height="90"></canvas>
    <script>
      const canvas = document.getElementById('game');
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#111'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      document.getElementById('start').addEventListener('click', () => {
        ctx.fillStyle = '#f5c542';
        ctx.fillRect(20, 20, 70, 40);
      });
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_click_visual",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_click_visual"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "game.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "click_start",
                "type": "browser",
                "action": "click",
                "selector_candidates": ["#start"],
                "expect": {"visual_change": True},
                "duration_ms": 500,
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["status"] == "PASSED"
    assert report["browser_tests"][1]["evaluation_result"] is True


def test_runner_click_falls_back_when_canvas_is_blocked_by_start_overlay(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        """<!doctype html>
<html>
  <body>
    <div style="position:relative;width:220px;height:120px">
      <canvas id="game" width="220" height="120"></canvas>
      <div id="overlay" style="position:absolute;inset:0;background:#0008">
        <button id="start">Start</button>
      </div>
    </div>
    <script>
      const canvas = document.getElementById('game');
      const ctx = canvas.getContext('2d');
      ctx.fillStyle = '#111'; ctx.fillRect(0, 0, canvas.width, canvas.height);
      document.getElementById('start').addEventListener('click', () => {
        document.getElementById('overlay').style.display = 'none';
        ctx.fillStyle = '#25d366';
        ctx.fillRect(20, 20, 80, 40);
      });
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_blocked_canvas",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_blocked_canvas"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "game.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "click_start",
                "type": "browser",
                "action": "click",
                "selector_candidates": ["canvas", "#start"],
                "expect": {"visual_change": True},
                "duration_ms": 500,
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["status"] == "PASSED"
    assert any("#start" in item for item in report["browser_tests"][1]["evidence"])


def test_runner_treats_screenshot_evaluate_target_as_visual_change(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "game.html").write_text(
        """<!doctype html>
<html>
  <body>
    <canvas id="game" width="220" height="120"></canvas>
    <script>
      const canvas = document.getElementById('game');
      const ctx = canvas.getContext('2d');
      let x = 0;
      function draw() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#3366ff';
        ctx.fillRect(x, 30, 50, 40);
        x = (x + 4) % canvas.width;
        requestAnimationFrame(draw);
      }
      draw();
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_screenshot_target",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_screenshot_target"},
        "patch_result": {"changed_files": ["game.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "game.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "game_renders",
                "type": "browser",
                "action": "evaluate",
                "target": "game_screenshot.png",
                "expect": {"visual_change": True},
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["action"] == "visual_change"
    assert report["browser_tests"][1]["evaluation_result"] is True


def test_runner_allows_observation_evaluate_without_expression(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        "<!doctype html><html><body><canvas id='game'></canvas></body></html>",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_observe_evaluate",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_observe_evaluate"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}/index.html",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "index.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "no_console_errors",
                "type": "browser",
                "action": "evaluate",
                "expect": {"no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["status"] == "PASSED"
    assert report["browser_tests"][1]["evaluation_result"] is True


def test_runner_treats_evaluate_html_target_as_page_observation(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "sokoban3d.html").write_text(
        """<!doctype html>
<html>
  <body>
    <canvas id="game" width="160" height="90"></canvas>
    <script>
      const ctx = document.getElementById('game').getContext('2d');
      ctx.fillStyle = '#8844ff';
      ctx.fillRect(10, 10, 60, 40);
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_html_evaluate",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_html_evaluate"},
        "patch_result": {"changed_files": ["sokoban3d.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}/sokoban3d.html",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "sokoban3d.html",
                "expect": {"page_loaded": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "game_renders",
                "type": "browser",
                "action": "evaluate",
                "target": "sokoban3d.html",
                "expect": {"visual_elements": ["floor", "walls", "player", "box"]},
                "timeout_sec": 10,
                "required": True,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "PASSED"
    assert report["browser_tests"][1]["status"] == "PASSED"
    assert report["browser_tests"][1]["evaluation_result"] is True


def test_runner_surfaces_browser_error_stack_and_location(tmp_path: Path) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        """<!doctype html>
<html>
  <body>
    <canvas id="game"></canvas>
    <script>
      const broken = undefined;
      broken.height = 10;
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_pageerror_evidence",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_pageerror_evidence"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}/index.html",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "index.html",
                "expect": {"page_loaded": True, "no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            }
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "FAILED"
    error = report["browser_tests"][0]["error"]
    assert "Cannot set properties of undefined" in error
    assert "index.html" in error
    console_path = tmp_path / report["artifacts"]["browser_console"]
    console_text = console_path.read_text(encoding="utf-8")
    assert "index.html" in console_text


def test_runner_fails_optional_interaction_with_fatal_console_error(
    tmp_path: Path,
) -> None:
    port = _free_port()
    (tmp_path / "index.html").write_text(
        """<!doctype html>
<html>
  <body>
    <button id="start">Start</button>
    <script>
      document.getElementById('start').addEventListener('click', () => {
        const level = undefined;
        level[0] = 1;
      });
    </script>
  </body>
</html>""",
        encoding="utf-8",
    )
    runner = RunnerAgent(vllm_client=None, skill_manager=None)
    runner_input = {
        "schema_version": "1.0",
        "task_id": "task_runner_optional_fatal",
        "round_id": 1,
        "workspace": str(tmp_path),
        "run_dir": ".harness/runs/run_001",
        "plan_contract": {"task_id": "task_runner_optional_fatal"},
        "patch_result": {"changed_files": ["index.html"]},
        "test_commands": [],
        "dev_server": {
            "enabled": True,
            "start_cmd": f"python -m http.server {port} --bind 127.0.0.1",
            "url": f"http://127.0.0.1:{port}/index.html",
            "ready_patterns": ["Serving HTTP on"],
            "timeout_sec": 20,
        },
        "smoke_tests": [
            {
                "id": "page_load",
                "type": "browser",
                "action": "goto",
                "target": "index.html",
                "expect": {"page_loaded": True, "no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": True,
            },
            {
                "id": "optional_start",
                "type": "browser",
                "action": "click",
                "selector_candidates": ["#start"],
                "expect": {"no_fatal_console_error": True},
                "timeout_sec": 10,
                "required": False,
            },
        ],
        "runner_limits": {
            "dev_server_timeout_sec": 20,
            "browser_test_timeout_sec": 10,
        },
        "permissions": {},
        "search_reports": [],
    }

    async def collect() -> None:
        async for _ in runner.run("runner-session", runner_input, tools=[]):
            pass

    asyncio.run(collect())

    report = runner.last_run_report
    assert report["status"] == "FAILED"
    assert report["browser_tests"][1]["required"] is False
    assert report["browser_tests"][1]["error_type"] == "PRODUCT_UI_ERROR"
