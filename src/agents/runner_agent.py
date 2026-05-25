import json
from utils.json_utils import safe_loads
import asyncio
import os
import re
import signal
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Mapping, Optional, cast

from loguru import logger

from .harness_engine import HarnessEngine
from .base_agent import BaseAgent

playwright_async_playwright: Any = None
try:
    from playwright.async_api import (
        async_playwright as _playwright_async_playwright,
    )

    playwright_async_playwright = _playwright_async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False



def _normalize_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _tail_text(value: Any, limit: int = 2000) -> str:
    text = str(value or "")
    return text[-limit:]


def _runner_input_commands(runner_input: Mapping[str, Any]) -> List[str]:
    commands: List[str] = []
    for item in runner_input.get("test_commands") or []:
        if isinstance(item, Mapping):
            cmd = str(item.get("cmd") or item.get("command") or "").strip()
        else:
            cmd = str(item).strip()
        if cmd:
            commands.append(cmd)
    dev_server: Dict[str, Any] = (
        dict(runner_input.get("dev_server") or {})
        if isinstance(runner_input.get("dev_server"), Mapping)
        else {}
    )
    start_cmd = str(dev_server.get("start_cmd") or "").strip()
    if start_cmd:
        commands.append(start_cmd)
    seen = set()
    result: List[str] = []
    for command in commands:
        if command not in seen:
            seen.add(command)
            result.append(command)
    return result


def _runner_command_specs(runner_input: Mapping[str, Any]) -> List[Dict[str, Any]]:
    specs: List[Dict[str, Any]] = []
    for index, item in enumerate(runner_input.get("test_commands") or [], start=1):
        if isinstance(item, Mapping):
            command = str(item.get("cmd") or item.get("command") or "").strip()
            if not command:
                continue
            specs.append(
                {
                    "name": str(item.get("name") or f"cmd_{index}").strip()
                    or f"cmd_{index}",
                    "cmd": command,
                    "timeout_sec": int(item.get("timeout_sec") or 120),
                    "required": bool(item.get("required", index == 1)),
                }
            )
        else:
            command = str(item).strip()
            if command:
                specs.append(
                    {
                        "name": f"cmd_{index}",
                        "cmd": command,
                        "timeout_sec": 120,
                        "required": index == 1,
                    }
                )
    return specs


async def _run_shell_command(
    command: str, *, cwd: Path, timeout_sec: int
) -> Dict[str, Any]:
    started = datetime.now().astimezone().isoformat(timespec="seconds")
    started_ts = time.time()
    process = await asyncio.create_subprocess_shell(
        command,
        cwd=str(cwd),
        env=os.environ.copy(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    timed_out = False
    try:
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=timeout_sec
        )
    except asyncio.TimeoutError:
        timed_out = True
        process.kill()
        await process.wait()
        stdout, stderr = b"", b"Command timed out"
    finished = datetime.now().astimezone().isoformat(timespec="seconds")
    return {
        "cmd": command,
        "exit_code": -1 if timed_out else int(process.returncode or 0),
        "status": (
            "TIMEOUT"
            if timed_out
            else ("PASSED" if process.returncode == 0 else "FAILED")
        ),
        "started_at": started,
        "finished_at": finished,
        "duration_sec": round(time.time() - started_ts, 3),
        "stdout": stdout.decode("utf-8", errors="replace") if stdout else "",
        "stderr": stderr.decode("utf-8", errors="replace") if stderr else "",
    }


async def _read_process_stream(
    stream: Optional[asyncio.StreamReader], buffer: List[str]
) -> None:
    if stream is None:
        return
    while True:
        chunk = await stream.readline()
        if not chunk:
            return
        buffer.append(chunk.decode("utf-8", errors="replace"))


async def _http_probe(url: str, *, timeout_sec: int) -> Dict[str, Any]:
    def _fetch() -> Dict[str, Any]:
        request = urllib.request.Request(
            url, headers={"User-Agent": "OBS-HarnessRunner/1.0"}
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout_sec) as response:
                body = response.read(200000).decode("utf-8", errors="replace")
                return {
                    "ok": 200 <= int(response.status or 0) < 400,
                    "status_code": int(response.status or 0),
                    "body": body,
                    "headers": dict(response.headers.items()),
                    "final_url": str(response.geturl() or url),
                    "error": "",
                }
        except urllib.error.HTTPError as exc:
            body = exc.read(200000).decode("utf-8", errors="replace")
            return {
                "ok": False,
                "status_code": int(exc.code or 0),
                "body": body,
                "headers": dict(exc.headers.items()) if exc.headers else {},
                "final_url": str(exc.geturl() or url),
                "error": str(exc),
            }
        except Exception as exc:
            return {
                "ok": False,
                "status_code": 0,
                "body": "",
                "headers": {},
                "final_url": url,
                "error": str(exc),
            }

    return await asyncio.to_thread(_fetch)


def _resolve_smoke_target(target: str, base_url: str) -> str:
    candidate = str(target or "").strip()
    base = str(base_url or "").strip()
    if not candidate:
        return base
    if candidate.startswith(("http://", "https://")):
        return candidate
    if base:
        parsed = urllib.parse.urlsplit(base)
        if parsed.scheme and parsed.netloc:
            base_for_join = base
            if not parsed.path or parsed.path.endswith("/"):
                base_for_join = base if base.endswith("/") else f"{base}/"
            return urllib.parse.urljoin(base_for_join, candidate.lstrip("/"))
        return urllib.parse.urljoin(
            base if base.endswith("/") else f"{base}/", candidate.lstrip("/")
        )
    return candidate


_INTERACTIVE_SMOKE_ACTIONS = {"click", "keyboard", "visual_change"}
_BROWSER_KEY_ALIASES = {
    "space": "Space",
    "enter": "Enter",
    "return": "Enter",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "up": "ArrowUp",
    "down": "ArrowDown",
}
_VISUAL_ARTIFACT_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".bmp",
    ".screenshot",
)


def _strip_html_tags(value: str) -> str:
    text = re.sub(r"<[^>]+>", " ", value or "")
    return re.sub(r"\s+", " ", text).strip()


def _normalize_browser_key(raw: str) -> str:
    raw_key = str(raw or "")
    if raw_key and raw_key.isspace():
        return "Space"
    key = raw_key.strip()
    return _BROWSER_KEY_ALIASES.get(key.lower(), key)


def _infer_browser_key(smoke_test: Mapping[str, Any]) -> str:
    hint = " ".join(
        str(smoke_test.get(name) or "")
        for name in ("id", "name", "target", "description", "label")
    ).lower()
    if "jump" in hint or "space" in hint:
        return "Space"
    if "attack" in hint or "shoot" in hint or "fire" in hint:
        return "j"
    if "left" in hint:
        return "ArrowLeft"
    if "right" in hint:
        return "ArrowRight"
    if "up" in hint or "forward" in hint or "move" in hint:
        return "w"
    if "down" in hint or "back" in hint:
        return "s"
    if "primary" in hint or "start" in hint or "action" in hint:
        return "Space"
    return ""


def _looks_like_visual_artifact_target(value: Any) -> bool:
    candidate = str(value or "").strip().lower()
    return bool(candidate) and candidate.endswith(_VISUAL_ARTIFACT_SUFFIXES)


def _looks_like_html_document_target(value: Any) -> bool:
    candidate = str(value or "").strip().lower().split("?", 1)[0].rstrip("/")
    return bool(candidate) and candidate.endswith((".html", ".htm"))


def _smoke_test_requires_live_browser(smoke_test: Mapping[str, Any]) -> bool:
    action = str(smoke_test.get("action") or "").strip()
    if action in _INTERACTIVE_SMOKE_ACTIONS:
        return True
    if action == "evaluate" and (smoke_test.get("key") or smoke_test.get("text")):
        return True
    expect = (
        smoke_test.get("expect")
        if isinstance(smoke_test.get("expect"), Mapping)
        else {}
    )
    return bool(
        (isinstance(expect, Mapping) and expect.get("visual_change"))
        or smoke_test.get("duration_ms")
        or (isinstance(expect, Mapping) and expect.get("game_responsive"))
        or (isinstance(expect, Mapping) and expect.get("no_fatal_console_error"))
        or (isinstance(expect, Mapping) and expect.get("visual_elements"))
    )


def _maybe_local_target(target: str, workspace: Path) -> str:
    candidate = str(target or "").strip()
    if not candidate:
        return ""
    local_path = Path(candidate)
    if not local_path.is_absolute():
        local_path = (workspace / candidate).resolve()
    if local_path.exists():
        return local_path.as_uri()
    return candidate


def _has_glob_pattern(value: str) -> bool:
    return any(ch in str(value or "") for ch in "*?[")


def _resolve_glob_browser_target(target: str, workspace: Path, base_url: str) -> str:
    parsed = urllib.parse.urlsplit(str(base_url or ""))
    if parsed.scheme in {"http", "https"} and parsed.path:
        base_path = (workspace / parsed.path.lstrip("/")).resolve()
        if base_path.is_file():
            return str(base_url)

    matches = sorted(
        path
        for path in workspace.glob(str(target or "").strip())
        if path.is_file()
    )
    if not matches:
        return str(target or "").strip()

    preferred = next((path for path in matches if path.name == "index.html"), matches[0])
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        relative = urllib.parse.quote(
            str(preferred.relative_to(workspace)).replace("\\", "/")
        )
        return urllib.parse.urlunsplit(
            (parsed.scheme, parsed.netloc, f"/{relative}", "", "")
        )
    return preferred.resolve().as_uri()


def _preferred_html_file(workspace: Path) -> Optional[Path]:
    files = sorted(path for path in workspace.glob("*.html") if path.is_file())
    if not files:
        return None
    return next((path for path in files if path.name == "index.html"), files[0])


def _resolve_missing_html_browser_target(target: str, workspace: Path, base_url: str) -> str:
    candidate = str(target or "").strip()
    parsed_target = urllib.parse.urlsplit(candidate)
    path_text = parsed_target.path if parsed_target.scheme else candidate
    if not path_text.lower().endswith((".html", ".htm")):
        return candidate

    local_path = Path(path_text.lstrip("/"))
    if not local_path.is_absolute():
        local_path = (workspace / local_path).resolve()
    if local_path.is_file():
        return candidate

    preferred = _preferred_html_file(workspace)
    if preferred is None:
        return candidate

    parsed_base = urllib.parse.urlsplit(
        candidate if parsed_target.scheme in {"http", "https"} else str(base_url or "")
    )
    if parsed_base.scheme in {"http", "https"} and parsed_base.netloc:
        relative = urllib.parse.quote(
            str(preferred.relative_to(workspace)).replace("\\", "/")
        )
        return urllib.parse.urlunsplit(
            (parsed_base.scheme, parsed_base.netloc, f"/{relative}", "", "")
        )
    return str(preferred.relative_to(workspace)).replace("\\", "/")


def _resolve_browser_navigation_target(
    smoke_test: Mapping[str, Any], workspace: Path, base_url: str
) -> str:
    action = str(smoke_test.get("action") or "goto").strip() or "goto"
    target = str(smoke_test.get("target") or "").strip()
    if target and _has_glob_pattern(target):
        target = _resolve_glob_browser_target(target, workspace, base_url)
    elif target:
        target = _resolve_missing_html_browser_target(target, workspace, base_url)
    if (
        action == "evaluate"
        and target
        and not _looks_like_html_document_target(target)
        and not target.startswith(("http://", "https://", "/"))
    ):
        return str(base_url or "").strip()
    if action in {"click", "keyboard"} and not target:
        return str(base_url or "").strip()
    resolved = _resolve_smoke_target(target, base_url)
    if resolved.startswith(("http://", "https://")):
        return resolved
    return _maybe_local_target(resolved, workspace)


def _evaluate_smoke_expression(expression: str, html: str) -> Optional[bool]:
    expr = str(expression or "").strip()
    if not expr:
        return None
    if "||" in expr:
        values = [_evaluate_smoke_expression(part, html) for part in expr.split("||")]
        if all(value is None for value in values):
            return None
        return any(bool(value) for value in values if value is not None)
    if "&&" in expr:
        values = [_evaluate_smoke_expression(part, html) for part in expr.split("&&")]
        if any(value is None for value in values):
            return None
        return all(bool(value) for value in values)

    lowered = expr.lower()
    visible_text = _strip_html_tags(html)
    html_lower = str(html or "").lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if re.search(r"document\.body\.innertext(?:\.trim\(\))?\.length\s*>\s*0", lowered):
        return bool(visible_text)

    includes_match = re.search(
        r"document\.body\.innertext\.includes\(([\'\"])(.*?)\1\)",
        expr,
        re.IGNORECASE,
    )
    if includes_match:
        return includes_match.group(2) in visible_text

    query_match = re.search(
        r"document\.queryselector\(([\'\"])(.*?)\1\)",
        expr,
        re.IGNORECASE,
    )
    if query_match:
        selector = query_match.group(2).strip().lower()
        if selector == "canvas":
            present = "<canvas" in html_lower
        elif selector.startswith("#"):
            present = (
                f'id="{selector[1:]}"' in html_lower
                or f"id='{selector[1:]}'" in html_lower
            )
        elif selector.startswith("."):
            present = selector[1:] in html_lower
        else:
            present = f"<{selector}" in html_lower
        if "!== null" in lowered or "!= null" in lowered or lowered.startswith("!!"):
            return present
        return present
    return None


async def _pick_first_selector(page: Any, candidates: List[str]) -> str:
    for candidate in candidates:
        selector = str(candidate or "").strip()
        if not selector:
            continue
        try:
            count = await page.locator(selector).count()
        except Exception:
            continue
        if count > 0:
            return selector
    return ""


async def _pick_first_visible_selector(page: Any, candidates: List[str]) -> str:
    fallback = ""
    for candidate in candidates:
        selector = str(candidate or "").strip()
        if not selector:
            continue
        try:
            locator = page.locator(selector).first
            count = await page.locator(selector).count()
            if count <= 0:
                continue
            fallback = fallback or selector
            if await locator.is_visible(timeout=500):
                return selector
        except Exception:
            continue
    return fallback


async def _click_first_successful_selector(
    page: Any, candidates: List[str], timeout_ms: int
) -> str:
    seen = set()
    selectors = [
        *[str(candidate or "").strip() for candidate in candidates],
        "button",
        "[role=button]",
        "input[type=button]",
        "input[type=submit]",
        "canvas",
        "body",
    ]
    last_error: Optional[Exception] = None
    per_selector_timeout = min(max(timeout_ms // 3, 1500), 3500)
    for selector in selectors:
        if not selector or selector in seen:
            continue
        seen.add(selector)
        try:
            locator = page.locator(selector).first
            if await page.locator(selector).count() <= 0:
                continue
            if not await locator.is_visible(timeout=500):
                continue
            await locator.click(timeout=per_selector_timeout)
            return selector
        except Exception as exc:
            last_error = exc
            continue
    if last_error is not None:
        raise last_error
    candidate_text = ", ".join(candidates)
    raise ValueError(f"No matching selector found from candidates: {candidate_text}")


def _looks_like_plain_selector(value: str) -> bool:
    candidate = str(value or "").strip()
    if not candidate:
        return False
    if candidate in {"body", "html"}:
        return True
    if candidate.startswith(("#", ".", "[", "button", "canvas")):
        return True
    return bool(re.fullmatch(r"[a-zA-Z][a-zA-Z0-9_-]*", candidate))


async def _canvas_nonblank(page: Any) -> bool:
    try:
        return bool(
            await page.evaluate(
                """() => {
                    const canvas = document.querySelector('canvas');
                    if (!canvas || !canvas.width || !canvas.height) return false;
                    try {
                        const ctx = canvas.getContext(
                        '2d',
                        { willReadFrequently: true }
                    );
                        if (!ctx) return false;
                        const w = Math.min(canvas.width, 96);
                        const h = Math.min(canvas.height, 96);
                        const pixels = ctx.getImageData(0, 0, w, h).data;
                        for (let i = 0; i < pixels.length; i += 4) {
                            if (
                                pixels[i + 3] > 0 &&
                                pixels[i] + pixels[i + 1] + pixels[i + 2] > 18
                            ) return true;
                        }
                    } catch (error) {}
                    return false;
                }"""
            )
        )
    except Exception:
        return False


async def _page_visually_changes(page: Any, timeout_ms: int, duration_ms: int = 0) -> bool:
    try:
        before = await page.screenshot(full_page=False)
        return await _page_visually_changes_from(
            page, before, timeout_ms, duration_ms
        )
    except Exception:
        return False


async def _page_visually_changes_from(
    page: Any, before: bytes, timeout_ms: int, duration_ms: int = 0
) -> bool:
    try:
        wait_ms = duration_ms or min(max(timeout_ms // 4, 700), 1500)
        await page.wait_for_timeout(min(max(wait_ms, 300), timeout_ms))
        after = await page.screenshot(full_page=False)
        if before != after:
            return True
        return await _canvas_nonblank(page)
    except Exception:
        return False


async def _check_browser_expectations(
    page: Any,
    expect: Mapping[str, Any],
    *,
    body_text: str,
    console_errors: List[str],
    evaluation_result: Any = None,
) -> str:
    page_loaded = bool(expect.get("page_loaded", False))
    if page_loaded and not body_text.strip():
        canvas_count = await page.locator("canvas").count()
        if canvas_count == 0:
            return "Page loaded but visible content was empty."

    contains = str(expect.get("contains") or expect.get("text") or "").strip()
    if contains and contains not in body_text:
        return f"Expected text not found: {contains}"

    text_contains_any = expect.get("text_contains_any")
    if isinstance(text_contains_any, list):
        options = [str(item).strip() for item in text_contains_any if str(item).strip()]
        if options and not any(option in body_text for option in options):
            return f"None of the expected text candidates were found: {options}"

    if expect.get("canvas_present"):
        if await page.locator("canvas").count() == 0:
            return "Expected canvas element was not found."

    if expect.get("canvas_nonblank") and not await _canvas_nonblank(page):
        return "Canvas was present but appeared blank."

    if (
        (expect.get("visual_change") or expect.get("game_responsive"))
        and evaluation_result is not True
    ):
        return "Expected visual change was not detected."

    if expect.get("no_fatal_console_error") and console_errors:
        for err in console_errors:
            if "HOST_LEAK_DETECTED" in str(err):
                return f"HOST_LEAK_DETECTED: {err}"
        return f"Console errors detected: {console_errors[0]}"

    if "result" in expect:
        expected = expect.get("result")
        if evaluation_result != expected:
            return f"Expected evaluation result {expected!r}, got {evaluation_result!r}"

    return ""


def _maybe_call(value: Any) -> Any:
    try:
        if callable(value):
            return value()
    except Exception:
        return None
    return value


def _format_browser_location(location: Any) -> str:
    location = _maybe_call(location)
    if not isinstance(location, Mapping):
        return ""
    url = str(location.get("url") or "").strip()
    line = location.get("lineNumber")
    column = location.get("columnNumber")
    if not url:
        return ""
    parts = [url]
    if line is not None:
        parts.append(str(line))
        if column is not None:
            parts.append(str(column))
    return ":".join(parts)


def _compact_browser_error(text: str, *, limit: int = 2000) -> str:
    text = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _format_console_message(message: Any) -> Dict[str, Any]:
    message_type = str(_maybe_call(getattr(message, "type", "")) or "")
    text = str(_maybe_call(getattr(message, "text", "")) or "")
    location = _format_browser_location(getattr(message, "location", None))
    formatted = text
    if location:
        formatted = f"{formatted}\nLocation: {location}".strip()
    return {
        "type": message_type,
        "text": _compact_browser_error(formatted),
        "location": location,
    }


def _format_page_error(error: Any) -> str:
    parts = [str(error or "").strip()]
    for attr in ("message", "name", "stack"):
        value = _maybe_call(getattr(error, attr, None))
        if value:
            value_text = str(value).strip()
            if value_text and all(value_text not in part for part in parts):
                label = attr.capitalize()
                parts.append(f"{label}: {value_text}")
    return _compact_browser_error("\n".join(part for part in parts if part))


async def _goto_with_domcontentloaded_recovery(
    page: Any, url: str, timeout_ms: int
) -> Any:
    try:
        return await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
    except Exception as exc:
        if "timeout" not in str(exc).lower():
            raise
        await page.wait_for_timeout(min(max(timeout_ms // 3, 1500), 5000))
        try:
            body_text = await page.locator("body").inner_text(timeout=1000)
        except Exception:
            body_text = ""
        try:
            canvas_count = await page.locator("canvas").count()
        except Exception:
            canvas_count = 0
        if page.url not in {"", "about:blank"} and (
            body_text.strip() or canvas_count > 0
        ):
            return None
        raise


async def _terminate_process(process: asyncio.subprocess.Process) -> List[str]:
    killed: List[str] = []
    if process.returncode is not None:
        return killed
    try:
        pgid = os.getpgid(process.pid)
    except Exception:
        pgid = None
    try:
        if pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            process.terminate()
        await asyncio.wait_for(process.wait(), timeout=5)
    except asyncio.TimeoutError:
        if pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
            killed.append(str(pgid))
        else:
            process.kill()
            killed.append(str(process.pid))
        await process.wait()
    except ProcessLookupError:
        pass
    return killed


def _normalize_run_report(
    raw_obj: Optional[Dict[str, Any]],
    runner_input: Mapping[str, Any],
    harness: HarnessEngine,
    *,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    source: Dict[str, Any] = dict(raw_obj or {})
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = (
        dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    )
    default_status = str(source.get("status") or "FAILED").upper()
    if default_status not in {
        "PASSED",
        "FAILED",
        "PARTIAL",
        "TIMEOUT",
        "SKIPPED",
        "INFRA_ERROR",
    }:
        default_status = "FAILED"
    run_dir = str(source.get("run_dir") or runner_input.get("run_dir") or "")
    artifacts: Dict[str, Any] = (
        dict(source.get("artifacts") or {})
        if isinstance(source.get("artifacts"), Mapping)
        else {}
    )
    report = {
        "schema_version": str(source.get("schema_version") or "1.0"),
        "task_id": str(
            source.get("task_id")
            or runner_input.get("task_id")
            or plan_contract.get("task_id")
            or "task_runtime_001"
        ),
        "round_id": int(source.get("round_id") or runner_input.get("round_id") or 1),
        "status": default_status,
        "started_at": str(source.get("started_at") or started_at or ""),
        "finished_at": str(source.get("finished_at") or finished_at or ""),
        "duration_sec": float(source.get("duration_sec") or duration_sec or 0.0),
        "commands": _normalize_list(source.get("commands")),
        "dev_server": (
            source.get("dev_server")
            if isinstance(source.get("dev_server"), Mapping)
            else {}
        ),
        "browser_tests": _normalize_list(source.get("browser_tests")),
        "artifacts": {
            "run_dir": run_dir,
            "screenshots": _normalize_list(artifacts.get("screenshots")),
            "traces": _normalize_list(artifacts.get("traces")),
            "logs": _normalize_list(artifacts.get("logs")),
            "browser_console": str(artifacts.get("browser_console") or ""),
        },
        "cleanup": (
            source.get("cleanup")
            if isinstance(source.get("cleanup"), Mapping)
            else {
                "browser_closed": False,
                "dev_server_stopped": False,
                "orphan_processes_killed": [],
            }
        ),
        "errors": _normalize_list(source.get("errors")),
        "summary": str(source.get("summary") or ""),
    }
    report["display_summary"] = harness.display_summary_for_output("Runner", report)
    return report


def _fallback_run_report(
    runner_input: Mapping[str, Any],
    error_message: str,
    harness: HarnessEngine,
    *,
    started_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    duration_sec: Optional[float] = None,
) -> Dict[str, Any]:
    plan_contract_raw = runner_input.get("plan_contract")
    plan_contract: Dict[str, Any] = (
        dict(plan_contract_raw) if isinstance(plan_contract_raw, Mapping) else {}
    )
    report = {
        "schema_version": "1.0",
        "task_id": str(
            runner_input.get("task_id")
            or plan_contract.get("task_id")
            or "task_runtime_001"
        ),
        "round_id": int(runner_input.get("round_id") or 1),
        "status": "INFRA_ERROR",
        "started_at": str(started_at or ""),
        "finished_at": str(finished_at or ""),
        "duration_sec": float(duration_sec or 0.0),
        "commands": [],
        "dev_server": {},
        "browser_tests": [],
        "artifacts": {
            "run_dir": str(runner_input.get("run_dir") or ""),
            "screenshots": [],
            "traces": [],
            "logs": [],
            "browser_console": "",
        },
        "cleanup": {
            "browser_closed": False,
            "dev_server_stopped": False,
            "orphan_processes_killed": [],
        },
        "errors": [
            {
                "type": "RUNNER_SCRIPT_ERROR",
                "root_category": "RUNNER",
                "message": error_message,
            }
        ],
        "summary": error_message,
    }
    report["display_summary"] = harness.display_summary_for_output("Runner", report)
    return report


class RunnerAgent(BaseAgent):
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt(
            "Runner", ""
        )
        self.last_run_report: Dict[str, Any] = {}

    