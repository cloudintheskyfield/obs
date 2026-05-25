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

playwright_async_playwright: Any = None
try:
    from playwright.async_api import (
        async_playwright as _playwright_async_playwright,
    )

    playwright_async_playwright = _playwright_async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False


def _find_first_json_object(raw: str) -> Optional[Dict[str, Any]]:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        parsed = safe_loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escape = False
    for idx in range(start, len(text)):
        ch = text[idx]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                candidate = text[start:idx + 1]
                try:
                    parsed = safe_loads(candidate)
                except Exception:
                    return None
                return parsed if isinstance(parsed, dict) else None
    return None


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


class RunnerAgent:
    def __init__(self, vllm_client: Any, skill_manager: Any) -> None:
        self.vllm_client = vllm_client
        self.skill_manager = skill_manager
        self.harness = HarnessEngine()
        self.system_prompt = self.harness.load_agent_prompt(
            "Runner", ""
        )
        self.last_run_report: Dict[str, Any] = {}

    def _sse(self, payload: Dict[str, Any]) -> str:
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    async def _start_dev_server(
        self,
        *,
        workspace: Path,
        run_dir: str,
        dev_server: Mapping[str, Any],
        allowed_commands: List[str],
        default_timeout_sec: int,
    ) -> Dict[str, Any]:
        start_cmd = str(dev_server.get("start_cmd") or "").strip()
        url = str(dev_server.get("url") or "").strip()
        ready_patterns = [
            str(item).strip()
            for item in (dev_server.get("ready_patterns") or [])
            if str(item).strip()
        ]
        timeout_sec = int(dev_server.get("timeout_sec") or default_timeout_sec or 60)
        log_path = workspace / run_dir / "logs" / "dev_server.log"
        relative_log = str(log_path.relative_to(workspace)).replace("\\", "/")

        report = {
            "enabled": bool(dev_server.get("enabled")),
            "start_cmd": start_cmd,
            "url": url,
            "ready_patterns": ready_patterns,
            "timeout_sec": timeout_sec,
            "status": "SKIPPED",
            "pid": None,
            "started_at": "",
            "finished_at": "",
            "duration_sec": 0.0,
            "ready": False,
            "ready_source": "",
            "matched_pattern": "",
            "log": relative_log,
        }

        if not start_cmd:
            report["status"] = "FAILED"
            report["finished_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return {
                "report": report,
                "errors": [
                    {
                        "type": "RUNNER_SCRIPT_ERROR",
                        "root_category": "RUNNER",
                        "message": "dev_server.enabled is true but start_cmd is empty.",
                    }
                ],
                "process": None,
                "stdout_buffer": [],
                "stderr_buffer": [],
                "stdout_task": None,
                "stderr_task": None,
            }

        if not self.harness.command_allowed(
            start_cmd, runner_input_commands=allowed_commands
        ):
            report["status"] = "FAILED"
            report["finished_at"] = (
                datetime.now().astimezone().isoformat(timespec="seconds")
            )
            return {
                "report": report,
                "errors": [
                    {
                        "type": "HARNESS_POLICY_VIOLATION",
                        "root_category": "HARNESS",
                        "message": (
                            "Blocked dev server command outside Runner "
                            f"input contract: {start_cmd}"
                        ),
                    }
                ],
                "process": None,
                "stdout_buffer": [],
                "stderr_buffer": [],
                "stdout_task": None,
                "stderr_task": None,
            }

        started_ts = time.time()
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        report["started_at"] = started_at
        process = await asyncio.create_subprocess_shell(
            start_cmd,
            cwd=str(workspace),
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        report["pid"] = int(process.pid or 0)
        stdout_buffer: List[str] = []
        stderr_buffer: List[str] = []
        stdout_task = asyncio.create_task(
            _read_process_stream(process.stdout, stdout_buffer)
        )
        stderr_task = asyncio.create_task(
            _read_process_stream(process.stderr, stderr_buffer)
        )
        probe_result: Dict[str, Any] = {
            "ok": False,
            "status_code": 0,
            "body": "",
            "error": "",
        }

        ready = False
        ready_source = ""
        matched_pattern = ""
        timeout_at = time.time() + timeout_sec
        while time.time() < timeout_at:
            combined = "".join(stdout_buffer[-200:]) + "".join(stderr_buffer[-200:])
            for pattern in ready_patterns:
                if pattern.lower() in combined.lower():
                    ready = True
                    ready_source = "log"
                    matched_pattern = pattern
                    break
            if ready:
                break
            if url:
                probe_result = await _http_probe(url, timeout_sec=2)
                if probe_result.get("ok"):
                    ready = True
                    ready_source = "http"
                    break
            if process.returncode is not None:
                break
            await asyncio.sleep(0.5)

        report["ready"] = ready
        report["ready_source"] = ready_source
        report["matched_pattern"] = matched_pattern
        report["duration_sec"] = round(time.time() - started_ts, 3)
        report["finished_at"] = (
            datetime.now().astimezone().isoformat(timespec="seconds")
        )

        errors: List[Dict[str, Any]] = []
        if ready:
            report["status"] = "PASSED"
        elif process.returncode is not None:
            report["status"] = "FAILED"
            errors.append(
                {
                    "type": "RUNNER_SCRIPT_ERROR",
                    "root_category": "RUNNER",
                    "message": _tail_text(
                        "".join(stderr_buffer)
                        or "".join(stdout_buffer)
                        or "Dev server exited before becoming ready."
                    ),
                }
            )
        else:
            report["status"] = "TIMEOUT"
            detail = (
                probe_result.get("error")
                or "Ready patterns were not observed before timeout."
            )
            errors.append(
                {
                    "type": "RUNNER_TIMEOUT",
                    "root_category": "RUNNER",
                    "message": f"Dev server did not become ready: {detail}",
                }
            )
        return {
            "report": report,
            "errors": errors,
            "process": process,
            "stdout_buffer": stdout_buffer,
            "stderr_buffer": stderr_buffer,
            "stdout_task": stdout_task,
            "stderr_task": stderr_task,
        }

    async def _stop_dev_server(
        self, ctx: Mapping[str, Any], *, workspace: Path
    ) -> Dict[str, Any]:
        process = ctx.get("process")
        stdout_task = ctx.get("stdout_task")
        stderr_task = ctx.get("stderr_task")
        stdout_buffer = list(ctx.get("stdout_buffer") or [])
        stderr_buffer = list(ctx.get("stderr_buffer") or [])
        report = dict(ctx.get("report") or {})
        orphan_processes_killed: List[str] = []

        if process is not None:
            orphan_processes_killed = await _terminate_process(process)
        if stdout_task is not None:
            await stdout_task
        if stderr_task is not None:
            await stderr_task

        log_rel = str(report.get("log") or "")
        if log_rel:
            log_path = workspace / log_rel
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(
                "".join(
                    [
                        f"$ {report.get('start_cmd') or ''}\n",
                        "[stdout]\n",
                        "".join(stdout_buffer),
                        "\n[stderr]\n",
                        "".join(stderr_buffer),
                    ]
                ),
                encoding="utf-8",
            )

        return {
            "report": report,
            "stdout": "".join(stdout_buffer),
            "stderr": "".join(stderr_buffer),
            "orphan_processes_killed": orphan_processes_killed,
        }

    async def _run_browser_smoke_test(
        self,
        smoke_test: Mapping[str, Any],
        *,
        workspace: Path,
        base_url: str,
        default_timeout_sec: int,
    ) -> Dict[str, Any]:
        started_ts = time.time()
        test_id = str(smoke_test.get("id") or smoke_test.get("action") or "smoke")
        action = str(smoke_test.get("action") or "goto").strip() or "goto"
        raw_target = str(smoke_test.get("target") or "").strip()
        target = _resolve_browser_navigation_target(
            smoke_test,
            workspace,
            base_url,
        )
        timeout_sec = int(smoke_test.get("timeout_sec") or default_timeout_sec or 15)
        required = bool(smoke_test.get("required", True))
        expect = (
            dict(smoke_test.get("expect") or {})
            if isinstance(smoke_test.get("expect"), Mapping)
            else {}
        )

        evidence: List[str] = []
        result: Dict[str, Any] = {
            "id": test_id,
            "type": str(smoke_test.get("type") or "browser"),
            "action": action,
            "target": target or raw_target,
            "required": required,
            "status": "SKIPPED",
            "duration_sec": 0.0,
            "http_status": None,
            "passed": False,
            "evidence": evidence,
            "error": "",
        }

        if not target:
            result["status"] = "FAILED"
            result["error"] = (
                "Smoke test target is empty and no dev server url is available."
            )
            result["error_type"] = "RUNNER_BROWSER_ERROR"
            result["root_category"] = "RUNNER"
            result["duration_sec"] = round(time.time() - started_ts, 3)
            return result

        if action not in {"goto", "evaluate"}:
            result["status"] = "FAILED"
            result["error"] = (
                f"Unsupported smoke test action in deterministic Runner: {action}"
            )
            result["error_type"] = "RUNNER_BROWSER_ERROR"
            result["root_category"] = "RUNNER"
            result["duration_sec"] = round(time.time() - started_ts, 3)
            return result

        if target.startswith(("http://", "https://")):
            probe = await _http_probe(target, timeout_sec=timeout_sec)
        else:
            local_path = Path(target)
            if not local_path.is_absolute():
                local_path = (workspace / target).resolve()
            if local_path.exists() and local_path.is_file():
                body = local_path.read_text(encoding="utf-8", errors="replace")
                probe = {
                    "ok": True,
                    "status_code": 200,
                    "body": body,
                    "headers": {},
                    "final_url": str(local_path),
                    "error": "",
                }
            else:
                probe = {
                    "ok": False,
                    "status_code": 0,
                    "body": "",
                    "headers": {},
                    "final_url": str(local_path),
                    "error": f"Local smoke test target not found: {local_path}",
                }
        result["http_status"] = int(probe.get("status_code") or 0) or None
        if not probe.get("ok"):
            result["status"] = "FAILED"
            result["error"] = str(probe.get("error") or f"GET {target} failed")
            result["error_type"] = "PRODUCT_RUNTIME_ERROR"
            result["root_category"] = "PRODUCT"
            result["evidence"] = [
                f"GET {target} -> {probe.get('status_code') or 'ERR'}"
            ]
            result["duration_sec"] = round(time.time() - started_ts, 3)
            return result

        body = str(probe.get("body") or "")
        visible_text = _strip_html_tags(body)
        failed_reason = ""
        evaluation_result = None
        if action == "goto":
            contains = str(expect.get("contains") or expect.get("text") or "").strip()
            page_loaded = bool(expect.get("page_loaded", True))
            if page_loaded and not visible_text and "<canvas" not in body.lower():
                failed_reason = "Page responded but visible content was empty."
            elif contains and contains not in visible_text and contains not in body:
                failed_reason = f"Expected text not found: {contains}"
        else:
            evaluation_result = _evaluate_smoke_expression(raw_target, body)
            result["evaluation_result"] = evaluation_result
            if evaluation_result is None:
                failed_reason = (
                    "Unsupported evaluate expression in deterministic Runner: "
                    f"{raw_target}"
                )
                result["error_type"] = "RUNNER_BROWSER_ERROR"
                result["root_category"] = "RUNNER"
            elif "result" in expect and evaluation_result != expect.get("result"):
                failed_reason = (
                    f"Expected evaluation result {expect.get('result')!r}, "
                    f"got {evaluation_result!r}"
                )

        if expect.get("no_fatal_console_error"):
            evidence.append("No browser console was collected in deterministic mode.")

        if failed_reason:
            result["status"] = "FAILED"
            result["error"] = failed_reason
            result.setdefault("error_type", "PRODUCT_UI_ERROR")
            result.setdefault("root_category", "PRODUCT")
            result["evidence"] = [
                f"GET {target} -> {probe.get('status_code')}",
                *evidence,
            ]
        else:
            result["status"] = "PASSED"
            result["passed"] = True
            result["evidence"] = [
                f"GET {target} -> {probe.get('status_code')}",
                *evidence,
            ]
            if action == "evaluate":
                result["evidence"].append(
                    f"Evaluated expression -> {evaluation_result!r}"
                )
        result["duration_sec"] = round(time.time() - started_ts, 3)
        return result

    async def _run_live_browser_smoke_tests(
        self,
        smoke_tests: List[Dict[str, Any]],
        *,
        workspace: Path,
        run_dir: str,
        base_url: str,
        default_timeout_sec: int,
    ) -> Dict[str, Any]:
        browser_tests: List[Dict[str, Any]] = []
        screenshots: List[str] = []
        browser_console_path = ""
        console_entries: List[Dict[str, Any]] = []
        console_errors: List[str] = []
        screenshot_dir = workspace / run_dir / "screenshots"
        screenshot_dir.mkdir(parents=True, exist_ok=True)

        def _on_console(message: Any) -> None:
            try:
                entry = _format_console_message(message)
                text = str(entry.get("text") or "")
                console_entries.append(entry)
                if entry["type"] == "error":
                    # Filter out host-side React hydration errors or minor warnings
                    lower_text = text.lower()
                    if "pointer lock" in lower_text or "wrongdocumenterror" in lower_text:
                        return
                    if "hydration error" in lower_text or "cannot be a descendant of" in lower_text:
                        if "app-shell" in lower_text or "sidebar" in lower_text or "history-panel" in lower_text:
                            # This is a strong indicator we hit the host UI
                            console_errors.append(f"HOST_LEAK_DETECTED: {text}")
                            return
                    console_errors.append(text)
            except Exception:
                pass

        def _on_page_error(error: Any) -> None:
            text = _format_page_error(error)
            console_entries.append({"type": "pageerror", "text": text})
            # Filter out host-side React hydration errors
            lower_text = text.lower()
            if "pointer lock" in lower_text or "wrongdocumenterror" in lower_text:
                return
            if "hydration error" in lower_text or "cannot be a descendant of" in lower_text:
                if "app-shell" in lower_text or "sidebar" in lower_text or "history-panel" in lower_text:
                    console_errors.append(f"HOST_LEAK_DETECTED: {text}")
                    return
            console_errors.append(text)

        try:
            playwright_factory = cast(Any, playwright_async_playwright)
            async with playwright_factory() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-web-security",
                    ],
                )
                context = await browser.new_context(
                    viewport={"width": 1280, "height": 720}
                )
                page = await context.new_page()
                page.on("console", _on_console)
                page.on("pageerror", _on_page_error)

                for index, smoke_test in enumerate(smoke_tests, start=1):
                    started_ts = time.time()
                    test_id = str(
                        smoke_test.get("id")
                        or smoke_test.get("action")
                        or f"smoke_{index}"
                    )
                    action = str(smoke_test.get("action") or "goto").strip() or "goto"
                    timeout_sec = int(
                        smoke_test.get("timeout_sec") or default_timeout_sec or 15
                    )
                    timeout_ms = timeout_sec * 1000
                    required = bool(smoke_test.get("required", True))
                    expect = (
                        dict(smoke_test.get("expect") or {})
                        if isinstance(smoke_test.get("expect"), Mapping)
                        else {}
                    )
                    if action == "evaluate" and not (
                        str(smoke_test.get("target") or "").strip()
                        or str(smoke_test.get("expression") or "").strip()
                        or str(smoke_test.get("selector") or "").strip()
                        or smoke_test.get("selector_candidates")
                    ):
                        if smoke_test.get("key") or smoke_test.get("text"):
                            action = "keyboard"
                        elif (
                            expect.get("visual_change")
                            or expect.get("game_responsive")
                            or smoke_test.get("duration_ms")
                        ):
                            action = "visual_change"
                    elif (
                        action == "evaluate"
                        and (
                            expect.get("visual_change")
                            or expect.get("game_responsive")
                        )
                        and _looks_like_visual_artifact_target(
                            smoke_test.get("target")
                            or smoke_test.get("expression")
                        )
                    ):
                        action = "visual_change"
                    elif (
                        action == "evaluate"
                        and _looks_like_html_document_target(
                            smoke_test.get("target")
                            or smoke_test.get("expression")
                        )
                    ):
                        smoke_test = dict(smoke_test)
                        smoke_test["selector_candidates"] = [
                            *list(smoke_test.get("selector_candidates") or []),
                            "canvas",
                            "body",
                        ]
                    navigation_target = _resolve_browser_navigation_target(
                        smoke_test, workspace, base_url
                    )
                    result: Dict[str, Any] = {
                        "id": test_id,
                        "type": str(smoke_test.get("type") or "browser"),
                        "action": action,
                        "target": navigation_target
                        or str(smoke_test.get("target") or ""),
                        "required": required,
                        "status": "SKIPPED",
                        "duration_sec": 0.0,
                        "http_status": None,
                        "passed": False,
                        "evidence": [],
                        "error": "",
                    }
                    evaluation_result: Any = None
                    try:
                        if action == "goto":
                            if not navigation_target:
                                raise ValueError(
                                    "Smoke test target is empty and no dev server "
                                    "url is available."
                                )
                            response = await _goto_with_domcontentloaded_recovery(
                                page,
                                navigation_target,
                                timeout_ms,
                            )
                            try:
                                await page.wait_for_load_state(
                                    "load", timeout=min(timeout_ms, 10000)
                                )
                            except Exception:
                                pass
                            result["http_status"] = (
                                response.status if response is not None else None
                            )
                            status_label = result["http_status"] or "OK"
                            result["evidence"].append(
                                f"GET {navigation_target} -> {status_label}"
                            )
                        elif action == "click":
                            if navigation_target and page.url in {"", "about:blank"}:
                                await _goto_with_domcontentloaded_recovery(
                                    page,
                                    navigation_target,
                                    timeout_ms,
                                )
                            candidates = [
                                *[
                                    str(item).strip()
                                    for item in (
                                        smoke_test.get("selector_candidates") or []
                                    )
                                    if str(item).strip()
                                ],
                                    str(smoke_test.get("selector") or "").strip(),
                            ]
                            visual_before = None
                            if expect.get("visual_change") or expect.get(
                                "game_responsive"
                            ):
                                visual_before = await page.screenshot(full_page=False)
                            selector = await _click_first_successful_selector(
                                page, candidates, timeout_ms
                            )
                            result["evidence"].append(f"Clicked selector: {selector}")
                            if visual_before is not None:
                                evaluation_result = await _page_visually_changes_from(
                                    page,
                                    visual_before,
                                    timeout_ms,
                                    int(smoke_test.get("duration_ms") or 0),
                                )
                                result["evaluation_result"] = evaluation_result
                                result["evidence"].append(
                                    "Visual change after click -> "
                                    f"{evaluation_result!r}"
                                )
                        elif action == "keyboard":
                            if navigation_target and page.url in {"", "about:blank"}:
                                await _goto_with_domcontentloaded_recovery(
                                    page,
                                    navigation_target,
                                    timeout_ms,
                                )
                            key = _normalize_browser_key(
                                str(
                                    smoke_test.get("key")
                                    or smoke_test.get("text")
                                    or ""
                                )
                            )
                            if not key:
                                key = _infer_browser_key(smoke_test)
                            if not key:
                                raise ValueError("keyboard smoke test requires key")
                            await page.keyboard.press(key)
                            result["evidence"].append(f"Pressed key: {key}")
                            if expect.get("visual_change") or expect.get(
                                "game_responsive"
                            ):
                                evaluation_result = await _page_visually_changes(
                                    page,
                                    timeout_ms,
                                    int(smoke_test.get("duration_ms") or 0),
                                )
                                result["evaluation_result"] = evaluation_result
                                result["evidence"].append(
                                    "Visual change after key -> "
                                    f"{evaluation_result!r}"
                                )
                        elif action == "visual_change":
                            if navigation_target and page.url in {"", "about:blank"}:
                                await _goto_with_domcontentloaded_recovery(
                                    page,
                                    navigation_target,
                                    timeout_ms,
                                )
                            evaluation_result = await _page_visually_changes(
                                page,
                                timeout_ms,
                                int(smoke_test.get("duration_ms") or 0),
                            )
                            result["evaluation_result"] = evaluation_result
                            result["evidence"].append(
                                "Visual change detected -> "
                                f"{evaluation_result!r}"
                            )
                        elif action == "evaluate":
                            if navigation_target and page.url in {"", "about:blank"}:
                                await _goto_with_domcontentloaded_recovery(
                                    page,
                                    navigation_target,
                                    timeout_ms,
                                )
                            expression = str(
                                smoke_test.get("target")
                                or smoke_test.get("expression")
                                or ""
                            ).strip()
                            candidates = [
                                *[
                                    str(item).strip()
                                    for item in (
                                        smoke_test.get("selector_candidates") or []
                                    )
                                    if str(item).strip()
                                ],
                                str(smoke_test.get("selector") or "").strip(),
                            ]
                            selector = await _pick_first_selector(page, candidates)
                            if not selector and _looks_like_plain_selector(expression):
                                selector = await _pick_first_selector(page, [expression])
                            if selector:
                                if selector == "canvas":
                                    evaluation_result = await _canvas_nonblank(page)
                                else:
                                    evaluation_result = await page.locator(
                                        selector
                                    ).first.inner_text(timeout=timeout_ms)
                                result["evidence"].append(
                                    f"Evaluated selector {selector} -> "
                                    f"{evaluation_result!r}"
                                )
                            else:
                                if (
                                    not expression
                                    or _looks_like_html_document_target(expression)
                                ):
                                    evaluation_result = True
                                    result["evidence"].append(
                                        "Observed page state without expression"
                                    )
                                else:
                                    evaluation_result = await page.evaluate(
                                        f"() => ({expression})"
                                    )
                                    result["evidence"].append(
                                        "Evaluated expression -> "
                                        f"{evaluation_result!r}"
                                    )
                            result["evaluation_result"] = evaluation_result
                        else:
                            raise ValueError(
                                "Unsupported smoke test action in browser Runner: "
                                f"{action}"
                            )

                        await page.wait_for_timeout(300)
                        try:
                            body_text = await page.locator("body").inner_text(
                                timeout=2000
                            )
                        except Exception:
                            body_text = ""
                        failed_reason = await _check_browser_expectations(
                            page,
                            expect,
                            body_text=body_text,
                            console_errors=console_errors,
                            evaluation_result=evaluation_result,
                        )
                        safe_test_id = re.sub(
                            r"[^a-zA-Z0-9._-]+", "_", test_id
                        )
                        screenshot_path = (
                            screenshot_dir / f"{index:02d}_{safe_test_id}.png"
                        )
                        await page.screenshot(
                            path=str(screenshot_path), full_page=False
                        )
                        relative_screenshot = str(
                            screenshot_path.relative_to(workspace)
                        ).replace("\\", "/")
                        screenshots.append(relative_screenshot)
                        result["evidence"].append(f"Screenshot: {relative_screenshot}")
                        if failed_reason:
                            result["status"] = "FAILED"
                            result["error"] = failed_reason
                            if "HOST_LEAK_DETECTED" in failed_reason:
                                result["error_type"] = "RUNNER_PORT_ERROR"
                                result["root_category"] = "RUNNER"
                            else:
                                result["error_type"] = "PRODUCT_UI_ERROR"
                                result["root_category"] = "PRODUCT"
                        else:
                            result["status"] = "PASSED"
                            result["passed"] = True
                    except ValueError as exc:
                        result["status"] = "FAILED"
                        result["error"] = str(exc)
                        result["error_type"] = "RUNNER_CONFIG_ERROR"
                        result["root_category"] = "RUNNER"
                    except Exception as exc:
                        result["status"] = "FAILED"
                        result["error"] = str(exc)
                        result["error_type"] = "RUNNER_BROWSER_ERROR"
                        result["root_category"] = "RUNNER"
                    result["duration_sec"] = round(time.time() - started_ts, 3)
                    browser_tests.append(result)
                    if result["status"] != "PASSED" and result.get("required", True):
                        break

                await context.close()
                await browser.close()
        except Exception as exc:
            return {
                "browser_tests": browser_tests,
                "screenshots": screenshots,
                "browser_console": browser_console_path,
                "launch_error": str(exc),
            }

        if console_entries:
            console_path = workspace / run_dir / "browser_console.json"
            console_path.write_text(
                json.dumps(console_entries, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            browser_console_path = str(console_path.relative_to(workspace)).replace(
                "\\", "/"
            )

        return {
            "browser_tests": browser_tests,
            "screenshots": screenshots,
            "browser_console": browser_console_path,
            "launch_error": "",
        }

    async def _run_controlled_commands(
        self,
        runner_input: Mapping[str, Any],
        *,
        started_at: str,
        started_ts: float,
    ) -> Dict[str, Any]:
        workspace = (
            Path(str(runner_input.get("workspace") or ".")).expanduser().resolve()
        )
        workspace.mkdir(parents=True, exist_ok=True)
        run_dir = str(runner_input.get("run_dir") or ".harness/runs/run_001")
        log_dir = workspace / run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        command_specs = _runner_command_specs(runner_input)
        smoke_tests = [
            dict(item)
            for item in (runner_input.get("smoke_tests") or [])
            if isinstance(item, Mapping)
        ]
        runner_limits = (
            dict(runner_input.get("runner_limits") or {})
            if isinstance(runner_input.get("runner_limits"), Mapping)
            else {}
        )
        allowed_commands = _runner_input_commands(runner_input)
        dev_server_cfg = (
            dict(runner_input.get("dev_server") or {})
            if isinstance(runner_input.get("dev_server"), Mapping)
            else {}
        )
        dev_server_enabled = bool(dev_server_cfg.get("enabled"))
        commands: List[Dict[str, Any]] = []
        browser_tests: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        artifact_logs: List[str] = []
        artifact_screenshots: List[str] = []
        browser_console_artifact = ""
        dev_server_report: Dict[str, Any] = {}
        cleanup = {
            "browser_closed": True,
            "dev_server_stopped": not dev_server_enabled,
            "orphan_processes_killed": [],
        }
        dev_server_ctx: Optional[Dict[str, Any]] = None

        try:
            for spec in command_specs:
                command = str(spec.get("cmd") or "")
                if not self.harness.command_allowed(
                    command, runner_input_commands=allowed_commands
                ):
                    errors.append(
                        {
                            "type": "HARNESS_POLICY_VIOLATION",
                            "root_category": "HARNESS",
                            "message": (
                                "Blocked command outside Runner input "
                                f"contract: {command}"
                            ),
                        }
                    )
                    commands.append({**spec, "status": "BLOCKED", "exit_code": None})
                    if spec.get("required", True):
                        break
                    continue

                result = await _run_shell_command(
                    command,
                    cwd=workspace,
                    timeout_sec=int(
                        spec.get("timeout_sec")
                        or runner_limits.get("command_timeout_sec")
                        or 120
                    ),
                )
                log_path = (
                    log_dir
                    / f"{str(spec.get('name') or 'command').replace('/', '_')}.log"
                )
                log_path.write_text(
                    "\n".join(
                        [
                            f"$ {command}",
                            f"status: {result['status']}",
                            f"exit_code: {result['exit_code']}",
                            "",
                            "[stdout]",
                            str(result.get("stdout") or ""),
                            "",
                            "[stderr]",
                            str(result.get("stderr") or ""),
                        ]
                    ),
                    encoding="utf-8",
                )
                relative_log = str(log_path.relative_to(workspace)).replace("\\", "/")
                artifact_logs.append(relative_log)
                command_record = {
                    **spec,
                    "status": result["status"],
                    "exit_code": result["exit_code"],
                    "duration_sec": result["duration_sec"],
                    "stdout_tail": _tail_text(result.get("stdout")),
                    "stderr_tail": _tail_text(result.get("stderr")),
                    "log": relative_log,
                }
                commands.append(command_record)
                if result["status"] != "PASSED":
                    errors.append(
                        {
                            "type": (
                                "RUNNER_TIMEOUT"
                                if result["status"] == "TIMEOUT"
                                else "PRODUCT_BUILD_ERROR"
                            ),
                            "root_category": (
                                "RUNNER" if result["status"] == "TIMEOUT" else "PRODUCT"
                            ),
                            "message": _tail_text(
                                result.get("stderr")
                                or result.get("stdout")
                                or f"Command failed: {command}"
                            ),
                            "command": command,
                        }
                    )
                    if spec.get("required", True):
                        break

            required_command_failed = any(
                command.get("required", True)
                and command.get("status") not in {"PASSED"}
                for command in commands
            )

            if not required_command_failed and dev_server_enabled:
                dev_server_ctx = await self._start_dev_server(
                    workspace=workspace,
                    run_dir=run_dir,
                    dev_server=dev_server_cfg,
                    allowed_commands=allowed_commands,
                    default_timeout_sec=int(
                        runner_limits.get("dev_server_timeout_sec") or 60
                    ),
                )
                dev_server_report = dict(dev_server_ctx.get("report") or {})
                errors.extend(list(dev_server_ctx.get("errors") or []))
                if dev_server_report.get("log"):
                    artifact_logs.append(str(dev_server_report.get("log")))

            dev_server_ready = not dev_server_enabled or bool(
                dev_server_report.get("ready")
            )
            if smoke_tests and dev_server_ready:
                base_url = str(
                    dev_server_report.get("url") or dev_server_cfg.get("url") or ""
                )
                requires_live_browser = any(
                    _smoke_test_requires_live_browser(item)
                    for item in smoke_tests
                )
                if requires_live_browser and PLAYWRIGHT_AVAILABLE:
                    live_browser = await self._run_live_browser_smoke_tests(
                        smoke_tests,
                        workspace=workspace,
                        run_dir=run_dir,
                        base_url=base_url,
                        default_timeout_sec=int(
                            runner_limits.get("browser_test_timeout_sec") or 60
                        ),
                    )
                    browser_tests.extend(list(live_browser.get("browser_tests") or []))
                    artifact_screenshots.extend(
                        list(live_browser.get("screenshots") or [])
                    )
                    browser_console_artifact = str(
                        live_browser.get("browser_console") or ""
                    )
                    launch_error = str(live_browser.get("launch_error") or "")
                    if launch_error:
                        errors.append(
                            {
                                "type": "RUNNER_BROWSER_ERROR",
                                "root_category": "RUNNER",
                                "message": launch_error,
                            }
                        )
                else:
                    for smoke_test in smoke_tests:
                        browser_test = await self._run_browser_smoke_test(
                            smoke_test,
                            workspace=workspace,
                            base_url=base_url,
                            default_timeout_sec=int(
                                runner_limits.get("browser_test_timeout_sec") or 60
                            ),
                        )
                        browser_tests.append(browser_test)
                        if browser_test["status"] != "PASSED" and browser_test.get(
                            "required", True
                        ):
                            break

                for browser_test in browser_tests:
                    if browser_test["status"] != "PASSED" and browser_test.get(
                        "required", True
                    ):
                        errors.append(
                            {
                                "type": str(
                                    browser_test.get("error_type")
                                    or "RUNNER_BROWSER_ERROR"
                                ),
                                "root_category": str(
                                    browser_test.get("root_category") or "RUNNER"
                                ),
                                "message": str(
                                    browser_test.get("error")
                                    or f"Smoke test failed: {browser_test.get('id')}"
                                ),
                                "smoke_test_id": browser_test.get("id"),
                            }
                        )
                        break
            elif smoke_tests and dev_server_enabled and not dev_server_ready:
                for smoke_test in smoke_tests:
                    browser_tests.append(
                        {
                            "id": str(
                                smoke_test.get("id")
                                or smoke_test.get("action")
                                or "smoke"
                            ),
                            "type": str(smoke_test.get("type") or "browser"),
                            "action": str(smoke_test.get("action") or "goto"),
                            "target": _resolve_smoke_target(
                                str(smoke_test.get("target") or ""),
                                str(dev_server_cfg.get("url") or ""),
                            ),
                            "required": bool(smoke_test.get("required", True)),
                            "status": "SKIPPED",
                            "duration_sec": 0.0,
                            "http_status": None,
                            "passed": False,
                            "evidence": [
                                "Smoke test skipped because dev server was not ready."
                            ],
                            "error": "",
                        }
                    )
        finally:
            if dev_server_ctx is not None:
                stopped = await self._stop_dev_server(
                    dev_server_ctx, workspace=workspace
                )
                cleanup["dev_server_stopped"] = True
                cleanup["orphan_processes_killed"] = list(
                    stopped.get("orphan_processes_killed") or []
                )
                if dev_server_report and not dev_server_report.get("status"):
                    dev_server_report = dict(stopped.get("report") or dev_server_report)
            elif not dev_server_enabled:
                cleanup["dev_server_stopped"] = True

        has_work = bool(command_specs or dev_server_enabled or smoke_tests)
        required_browser_failed = any(
            item.get("required", True)
            and item.get("status") not in {"PASSED", "SKIPPED"}
            for item in browser_tests
        )
        fatal_browser_failed = any(
            item.get("status") not in {"PASSED", "SKIPPED"}
            and str(item.get("error_type") or "")
            in {"PRODUCT_UI_ERROR", "RUNNER_PORT_ERROR", "HOST_LEAK_DETECTED"}
            for item in browser_tests
        )
        if not has_work:
            status = "SKIPPED"
        elif any(error.get("type") == "RUNNER_TIMEOUT" for error in errors):
            status = "TIMEOUT"
        elif (
            required_command_failed
            or required_browser_failed
            or fatal_browser_failed
            or any(error.get("type") == "RUNNER_SCRIPT_ERROR" for error in errors)
        ):
            status = "FAILED"
        elif errors:
            status = "PARTIAL"
        else:
            status = "PASSED"

        finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
        summary_parts: List[str] = []
        if commands:
            summary_parts.append(f"Executed {len(commands)} command(s)")
        if dev_server_enabled:
            if dev_server_report.get("ready"):
                summary_parts.append("started dev server")
            else:
                summary_parts.append("dev server was not ready")
        if browser_tests:
            passed_tests = sum(
                1 for item in browser_tests if item.get("status") == "PASSED"
            )
            summary_parts.append(
                f"completed {passed_tests}/{len(browser_tests)} smoke test(s)"
            )
        if not summary_parts:
            summary_parts.append("No Runner commands or smoke tests were provided.")

        report = {
            "schema_version": "1.0",
            "task_id": str(runner_input.get("task_id") or "task_runtime_001"),
            "round_id": int(runner_input.get("round_id") or 1),
            "status": status,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_sec": round(time.time() - started_ts, 3),
            "commands": commands,
            "dev_server": dev_server_report,
            "browser_tests": browser_tests,
            "artifacts": {
                "run_dir": run_dir,
                "screenshots": list(dict.fromkeys(artifact_screenshots)),
                "traces": [],
                "logs": list(dict.fromkeys(artifact_logs)),
                "browser_console": browser_console_artifact,
            },
            "cleanup": cleanup,
            "errors": errors,
            "summary": "; ".join(summary_parts),
        }
        report["display_summary"] = self.harness.display_summary_for_output(
            "Runner", report
        )
        return report

    async def run(
        self,
        session_id: str,
        runner_input: Mapping[str, Any],
        *,
        tools: List[Dict[str, Any]],
        model: Optional[str] = None,
        max_iterations: int = 8,
    ) -> AsyncGenerator[str, None]:
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Runner",
                "status": "running",
                "title": "执行验证与采集证据",
                "detail": "运行命令、页面检查与日志采集...",
                "session_id": session_id,
            }
        )

        runner_tools = self.harness.filter_tools_for_role("Runner", tools)
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self._build_user_prompt(runner_input)},
        ]

        raw_content = ""
        tool_step = 0
        run_report: Dict[str, Any] = {}
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        started_ts = time.time()

        deterministic_runner = (
            str(runner_input.get("execution_mode") or "").strip().lower()
            == "harness_controlled"
        )
        if self.vllm_client is None or deterministic_runner:
            run_report = await self._run_controlled_commands(
                runner_input,
                started_at=started_at,
                started_ts=started_ts,
            )

        for iteration in range(0 if run_report else max_iterations):
            assistant_message: Dict[str, Any] = {"role": "assistant", "content": ""}
            tool_calls: List[Dict[str, Any]] = []
            try:
                stream = await self.vllm_client.chat_completion(
                    messages=messages,
                    tools=runner_tools if runner_tools else None,
                    temperature=0.1,
                    max_tokens=2200,
                    stream=True,
                    model=model,
                )
                async for chunk in stream:
                    if isinstance(chunk, dict) and "__obs_phase" in chunk:
                        continue
                    if "choices" not in chunk or not chunk["choices"]:
                        continue
                    delta = chunk["choices"][0].get("delta", {})
                    piece = delta.get("content") or ""
                    if piece:
                        raw_content += piece
                        assistant_message["content"] += piece
                        yield self._sse(
                            {
                                "type": "agent_thinking",
                                "agent": "runner",
                                "delta": piece,
                                "session_id": session_id,
                            }
                        )
                    if "tool_calls" in delta and delta["tool_calls"]:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", len(tool_calls))
                            while len(tool_calls) <= idx:
                                tool_calls.append(
                                    {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                )
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            if "function" in tc:
                                if tc["function"].get("name"):
                                    tool_calls[idx]["function"]["name"] += tc[
                                        "function"
                                    ]["name"]
                                if tc["function"].get("arguments"):
                                    tool_calls[idx]["function"]["arguments"] += tc[
                                        "function"
                                    ]["arguments"]
            except Exception as exc:
                logger.warning(f"RunnerAgent iteration {iteration} model error: {exc}")
                finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                run_report = _fallback_run_report(
                    runner_input,
                    str(exc),
                    self.harness,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_sec=round(time.time() - started_ts, 3),
                )
                break

            if not tool_calls:
                finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                run_report = _normalize_run_report(
                    _find_first_json_object(assistant_message["content"]),
                    runner_input,
                    self.harness,
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_sec=round(time.time() - started_ts, 3),
                )
                break

            assistant_message["tool_calls"] = tool_calls
            messages.append(dict(assistant_message))

            allowed_commands = _runner_input_commands(runner_input)
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    raw_args = tc["function"]["arguments"]
                    tool_args = safe_loads(raw_args) if raw_args else {}
                except Exception:
                    tool_args = {}

                resolved_tool_name = (
                    self.skill_manager.resolve_skill_name_for_tool(tool_name)
                    or tool_name
                )
                if resolved_tool_name == "desktop-commander":
                    command = str(tool_args.get("command") or "").strip()
                    if not self.harness.command_allowed(
                        command,
                        runner_input_commands=allowed_commands,
                    ):
                        tool_args = {}
                        tool_name = tool_name or "desktop-commander.terminal"
                        tool_result = (
                            f"Blocked command outside Runner input contract: {command}"
                        )
                        yield self._sse(
                            {
                                "type": "agent_step",
                                "role": "Runner",
                                "status": "error",
                                "title": "Runner 命令被 Harness 拦截",
                                "detail": tool_result,
                                "session_id": session_id,
                            }
                        )
                        finished_at = (
                            datetime.now().astimezone().isoformat(timespec="seconds")
                        )
                        run_report = _fallback_run_report(
                            runner_input,
                            tool_result,
                            self.harness,
                            started_at=started_at,
                            finished_at=finished_at,
                            duration_sec=round(time.time() - started_ts, 3),
                        )
                        break

                tool_step += 1
                task_id = f"runner_step_{tool_step}"
                yield self._sse(
                    {
                        "type": "task_start",
                        "task_id": task_id,
                        "description": f"[Runner] {tool_name}",
                        "skill": tool_name,
                        "action": "tool",
                        "session_id": session_id,
                    }
                )

                tool_result = ""
                success = False
                try:
                    result = await self.skill_manager.execute_skill(
                        tool_name, **tool_args
                    )
                    tool_result = (
                        str(result.content)
                        if result.success
                        else f"Error: {result.error}"
                    )
                    success = result.success
                except Exception as exc:
                    tool_result = str(exc)

                yield self._sse(
                    {
                        "type": "task_complete",
                        "task_id": task_id,
                        "success": success,
                        "content": (
                            tool_result[:400] + "..."
                            if len(tool_result) > 400
                            else tool_result
                        ),
                        "description": f"[Runner] {tool_name}",
                        "session_id": session_id,
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id", "unknown"),
                        "name": tool_name,
                        "content": tool_result[:8000],
                    }
                )

        if not run_report:
            finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
            run_report = _fallback_run_report(
                runner_input,
                "Runner did not return a valid RunReport.",
                self.harness,
                started_at=started_at,
                finished_at=finished_at,
                duration_sec=round(time.time() - started_ts, 3),
            )

        self.last_run_report = run_report
        passed = run_report.get("status") == "PASSED"
        yield self._sse(
            {
                "type": "agent_step",
                "role": "Runner",
                "status": "success" if passed else "error",
                "title": "执行与证据采集完成" if passed else "执行与证据采集遇到问题",
                "detail": run_report.get("summary", ""),
                "session_id": session_id,
            }
        )

    @staticmethod
    def _build_user_prompt(runner_input: Mapping[str, Any]) -> str:
        return json.dumps(dict(runner_input), ensure_ascii=False, indent=2)
