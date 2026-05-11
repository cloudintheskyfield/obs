"""Computer Use Skill - Claude官方计算机使用技能"""
import base64
import io
import os
from typing import Optional, Dict, Any, Tuple, List
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None

try:
    from playwright.async_api import async_playwright, Page, Browser, BrowserContext
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Page = None
    Browser = None
    BrowserContext = None

from loguru import logger

from base_skill import BaseSkill, SkillResult

KEY_ALIASES: Dict[str, str] = {
    "return": "Enter",
    "enter": "Enter",
    "esc": "Escape",
    "escape": "Escape",
    "del": "Delete",
    "delete": "Delete",
    "backspace": "Backspace",
    "tab": "Tab",
    "space": "Space",
    "up": "ArrowUp",
    "down": "ArrowDown",
    "left": "ArrowLeft",
    "right": "ArrowRight",
    "home": "Home",
    "end": "End",
    "pageup": "PageUp",
    "pagedown": "PageDown",
    "ctrl+a": "Control+a",
    "ctrl+c": "Control+c",
    "ctrl+v": "Control+v",
    "ctrl+x": "Control+x",
    "ctrl+z": "Control+z",
    "ctrl+y": "Control+y",
    "ctrl+s": "Control+s",
    "ctrl+f": "Control+f",
    "ctrl+r": "Control+r",
    "ctrl+t": "Control+t",
    "ctrl+w": "Control+w",
    "cmd+a": "Meta+a",
    "cmd+c": "Meta+c",
    "cmd+v": "Meta+v",
    "cmd+x": "Meta+x",
    "cmd+z": "Meta+z",
    "cmd+s": "Meta+s",
    "cmd+r": "Meta+r",
    "cmd+t": "Meta+t",
    "cmd+w": "Meta+w",
    "f5": "F5",
    "f12": "F12",
}


class ComputerUseSkill(BaseSkill):
    """Computer Use Skill - 浏览器视口操作，所有坐标基于视口"""

    def __init__(self, screenshot_dir: str = "screenshots"):
        super().__init__(
            name="computer",
            description=(
                "Use a mouse and keyboard to interact with a computer, open web pages, and take screenshots. "
                "Actions: screenshot, navigate, scroll, mouse_move, left_click, right_click, middle_click, "
                "double_click, left_click_drag, type, key, cursor_position. "
                "Coordinates are viewport pixels from top-left (0,0)."
            )
        )

        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)

        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.playwright = None
        self.console_errors: List[str] = []
        self.headless = os.getenv("WEB_HEADLESS", "").lower() == "true"
        if os.getenv("RUNNING_IN_DOCKER", "").lower() == "true" and "DISPLAY" not in os.environ:
            self.headless = True

        self.add_parameter(
            "action",
            "str",
            "Action to perform: screenshot, navigate, scroll, mouse_move, left_click, right_click, "
            "middle_click, double_click, left_click_drag, type, key, cursor_position",
            True
        )
        self.add_parameter(
            "coordinate",
            "list",
            "[x, y] for mouse actions; [x1, y1, x2, y2] for drag",
            False
        )
        self.add_parameter(
            "text",
            "str",
            "Text to type (for 'type') or key name (for 'key', e.g. 'Enter', 'Tab', 'ctrl+c')",
            False
        )
        self.add_parameter(
            "url",
            "str",
            "URL to navigate to (for 'navigate')",
            False
        )
        self.add_parameter(
            "direction",
            "str",
            "Scroll direction: up, down, left, right (for 'scroll', default: down)",
            False
        )
        self.add_parameter(
            "amount",
            "int",
            "Scroll amount in steps (for 'scroll', default: 3)",
            False
        )

    async def _ensure_page(self):
        """确保浏览器和页面可用，按需恢复。"""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright not installed. Run: pip install playwright && playwright install chromium")

        if self.playwright is None:
            self.playwright = await async_playwright().start()

        if self.browser is None or not self.browser.is_connected():
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                ]
            )
            self.context = None
            self.page = None
            logger.info("Browser launched")

        if self.context is None:
            self.context = await self.browser.new_context(
                viewport={"width": 1280, "height": 720}
            )
            self.page = None
            logger.info("Browser context created")

        if self.page is None or self.page.is_closed():
            self.page = await self.context.new_page()
            self.console_errors = []
            self.page.on("console", self._record_console_message)
            self.page.on("pageerror", self._record_page_error)
            logger.info("New page created")

    def _record_console_message(self, message: Any) -> None:
        try:
            if getattr(message, "type", "") == "error":
                self.console_errors.append(str(getattr(message, "text", ""))[:300])
        except Exception:
            pass

    def _record_page_error(self, error: Any) -> None:
        try:
            self.console_errors.append(str(error)[:300])
        except Exception:
            pass

    async def _screenshot_b64(self, save: bool = True) -> str:
        """截取视口截图，返回 base64 字符串。"""
        await self._ensure_page()
        image_bytes = await self.page.screenshot(full_page=False)
        if save:
            ts = self._get_timestamp()
            path = self.screenshot_dir / f"screenshot_{ts}.png"
            path.write_bytes(image_bytes)
            logger.debug(f"Screenshot saved: {path}")
        return base64.b64encode(image_bytes).decode("utf-8")

    async def _page_context(self) -> str:
        """返回当前页面 URL 和标题，供 content 字段使用。"""
        try:
            url = self.page.url if self.page else ""
            title = await self.page.title() if self.page else ""
            if url and url != "about:blank":
                return f" | URL: {url}" + (f" | Title: {title}" if title else "")
        except Exception:
            pass
        return ""

    async def _page_diagnostics(self) -> str:
        """Return compact post-action UI evidence for evaluator decisions."""
        await self._ensure_page()
        try:
            data = await self.page.evaluate(
                """() => {
                    const isVisible = (el) => {
                        if (!el) return false;
                        const style = getComputedStyle(el);
                        const rect = el.getBoundingClientRect();
                        return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
                    };
                    const text = (document.body?.innerText || '').replace(/\\s+/g, ' ').trim().slice(0, 180);
                    const buttons = Array.from(document.querySelectorAll('button'))
                        .filter(isVisible)
                        .map((button) => (button.innerText || button.textContent || '').replace(/\\s+/g, ' ').trim())
                        .filter(Boolean)
                        .slice(0, 5)
                        .join('|');
                    const scoreEl = document.querySelector('#score, [data-score], .score, #score-display');
                    const healthEl = document.querySelector('#health, [data-health], .health, #health-display');
                    const activeScreen = Array.from(document.querySelectorAll('.screen.active, [data-state].active, [aria-hidden="false"]'))
                        .map((el) => el.id || el.getAttribute('data-state') || el.className || el.tagName)
                        .filter(Boolean)
                        .slice(0, 3)
                        .join('|');
                    let canvasNonblank = false;
                    let canvasInfo = 'none';
                    for (const canvas of Array.from(document.querySelectorAll('canvas'))) {
                        canvasInfo = `${canvas.width}x${canvas.height}`;
                        try {
                            const ctx = canvas.getContext('2d', { willReadFrequently: true });
                            if (!ctx || !canvas.width || !canvas.height) continue;
                            const w = Math.min(canvas.width, 96);
                            const h = Math.min(canvas.height, 96);
                            const pixels = ctx.getImageData(0, 0, w, h).data;
                            for (let i = 0; i < pixels.length; i += 4) {
                                if (pixels[i + 3] > 0 && pixels[i] + pixels[i + 1] + pixels[i + 2] > 18) {
                                    canvasNonblank = true;
                                    break;
                                }
                            }
                        } catch (error) {}
                        break;
                    }
                    const gameState = String(window.gameState || window.state || window.appState || '');
                    return {
                        text,
                        buttons,
                        score: (scoreEl?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
                        health: (healthEl?.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40),
                        activeScreen,
                        gameState,
                        canvasNonblank,
                        canvasInfo,
                    };
                }"""
            )
            return (
                f" | visible_text={data.get('text') or ''}"
                f" | buttons={data.get('buttons') or ''}"
                f" | score={data.get('score') or ''}"
                f" | health={data.get('health') or ''}"
                f" | active_screen={data.get('activeScreen') or ''}"
                f" | game_state={data.get('gameState') or ''}"
                f" | canvas_nonblank={str(bool(data.get('canvasNonblank'))).lower()}"
                f" | canvas={data.get('canvasInfo') or 'none'}"
                f" | console_errors={len(self.console_errors)}"
            )
        except Exception as exc:
            return f" | diagnostics_error={str(exc)[:160]} | console_errors={len(self.console_errors)}"

    def _annotate(self, b64: str, points: List[Tuple[int, int]]) -> str:
        """在截图上标注坐标点（红圈+十字）。"""
        if not PIL_AVAILABLE or not points:
            return b64
        try:
            img = Image.open(io.BytesIO(base64.b64decode(b64)))
            draw = ImageDraw.Draw(img)
            for x, y in points:
                r = 12
                draw.ellipse([x - r, y - r, x + r, y + r], outline="red", width=3)
                draw.line([x - r * 2, y, x + r * 2, y], fill="red", width=2)
                draw.line([x, y - r * 2, x, y + r * 2], fill="red", width=2)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Annotation failed: {e}")
            return b64

    @staticmethod
    def _get_timestamp() -> str:
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

    @staticmethod
    def _normalize_key(raw: str) -> str:
        return KEY_ALIASES.get(raw.strip().lower(), raw.strip())

    async def initialize(self):
        """兼容旧接口：确保页面可用。"""
        await self._ensure_page()

    async def cleanup(self):
        """关闭浏览器，释放资源。"""
        try:
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            logger.warning(f"Cleanup error: {e}")
        finally:
            self.page = None
            self.context = None
            self.browser = None
            self.playwright = None
        logger.info("Computer Use Skill cleaned up")

    async def execute(self, **kwargs) -> SkillResult:
        """执行 Computer Use 操作。"""
        action = kwargs.get("action")

        try:
            if action == "screenshot":
                await self._ensure_page()
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Screenshot taken{ctx}{diagnostics}",
                    metadata={"action": action}
                )

            elif action == "navigate":
                url = kwargs.get("url")
                if not url:
                    return SkillResult(success=False, error="navigate requires 'url' parameter")
                await self._ensure_page()
                self.console_errors = []
                try:
                    await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception:
                    pass
                try:
                    await self.page.wait_for_load_state("load", timeout=10000)
                except Exception:
                    pass
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Navigated to {url}{ctx}{diagnostics}",
                    metadata={"action": action, "url": url}
                )

            elif action == "scroll":
                await self._ensure_page()
                direction = (kwargs.get("direction") or "down").lower()
                amount = int(kwargs.get("amount") or 3)
                coordinate = kwargs.get("coordinate")
                delta_map = {
                    "up":    (0, -120 * amount),
                    "down":  (0, 120 * amount),
                    "left":  (-120 * amount, 0),
                    "right": (120 * amount, 0),
                }
                if direction not in delta_map:
                    return SkillResult(success=False, error=f"Invalid scroll direction '{direction}'. Use: up, down, left, right")
                dx, dy = delta_map[direction]
                if coordinate and len(coordinate) >= 2:
                    await self.page.mouse.move(coordinate[0], coordinate[1])
                await self.page.mouse.wheel(dx, dy)
                await self.page.wait_for_timeout(300)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Scrolled {direction} by {amount} steps{ctx}{diagnostics}",
                    metadata={"action": action, "direction": direction, "amount": amount}
                )

            elif action in ("left_click", "click"):
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 2:
                    return SkillResult(success=False, error="left_click requires coordinate [x, y]")
                await self._ensure_page()
                x, y = int(coordinate[0]), int(coordinate[1])
                await self.page.mouse.click(x, y)
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=self._annotate(b64, [(x, y)]),
                    content=f"Left clicked ({x}, {y}){ctx}{diagnostics}",
                    metadata={"action": "left_click", "coordinate": [x, y]}
                )

            elif action == "right_click":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 2:
                    return SkillResult(success=False, error="right_click requires coordinate [x, y]")
                await self._ensure_page()
                x, y = int(coordinate[0]), int(coordinate[1])
                await self.page.mouse.click(x, y, button="right")
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=self._annotate(b64, [(x, y)]),
                    content=f"Right clicked ({x}, {y}){ctx}{diagnostics}",
                    metadata={"action": action, "coordinate": [x, y]}
                )

            elif action == "middle_click":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 2:
                    return SkillResult(success=False, error="middle_click requires coordinate [x, y]")
                await self._ensure_page()
                x, y = int(coordinate[0]), int(coordinate[1])
                await self.page.mouse.click(x, y, button="middle")
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=self._annotate(b64, [(x, y)]),
                    content=f"Middle clicked ({x}, {y}){ctx}{diagnostics}",
                    metadata={"action": action, "coordinate": [x, y]}
                )

            elif action == "double_click":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 2:
                    return SkillResult(success=False, error="double_click requires coordinate [x, y]")
                await self._ensure_page()
                x, y = int(coordinate[0]), int(coordinate[1])
                await self.page.mouse.dblclick(x, y)
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=self._annotate(b64, [(x, y)]),
                    content=f"Double clicked ({x}, {y}){ctx}{diagnostics}",
                    metadata={"action": action, "coordinate": [x, y]}
                )

            elif action == "mouse_move":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 2:
                    return SkillResult(success=False, error="mouse_move requires coordinate [x, y]")
                await self._ensure_page()
                x, y = int(coordinate[0]), int(coordinate[1])
                await self.page.mouse.move(x, y)
                await self.page.wait_for_timeout(100)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Mouse moved to ({x}, {y}){ctx}{diagnostics}",
                    metadata={"action": action, "coordinate": [x, y]}
                )

            elif action == "left_click_drag":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) < 4:
                    return SkillResult(success=False, error="left_click_drag requires coordinate [x1, y1, x2, y2]")
                await self._ensure_page()
                x1, y1, x2, y2 = int(coordinate[0]), int(coordinate[1]), int(coordinate[2]), int(coordinate[3])
                await self.page.mouse.move(x1, y1)
                await self.page.mouse.down()
                await self.page.mouse.move(x2, y2, steps=10)
                await self.page.mouse.up()
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=self._annotate(b64, [(x1, y1), (x2, y2)]),
                    content=f"Dragged from ({x1}, {y1}) to ({x2}, {y2}){ctx}{diagnostics}",
                    metadata={"action": action, "coordinate": [x1, y1, x2, y2]}
                )

            elif action == "type":
                text = kwargs.get("text")
                if not text:
                    return SkillResult(success=False, error="type requires 'text' parameter")
                await self._ensure_page()
                await self.page.keyboard.type(str(text), delay=30)
                await self.page.wait_for_timeout(300)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Typed: '{text}'{ctx}{diagnostics}",
                    metadata={"action": action, "text": text}
                )

            elif action == "key":
                text = kwargs.get("text")
                if not text:
                    return SkillResult(success=False, error="key requires 'text' parameter (key name)")
                await self._ensure_page()
                key = self._normalize_key(str(text))
                await self.page.keyboard.press(key)
                await self.page.wait_for_timeout(400)
                b64 = await self._screenshot_b64()
                ctx = await self._page_context()
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Pressed key '{key}'{ctx}{diagnostics}",
                    metadata={"action": action, "key": key}
                )

            elif action == "cursor_position":
                await self._ensure_page()
                b64 = await self._screenshot_b64()
                url = self.page.url if self.page else ""
                try:
                    title = await self.page.title() if self.page else ""
                except Exception:
                    title = ""
                diagnostics = await self._page_diagnostics()
                return SkillResult(
                    success=True,
                    base64_image=b64,
                    content=f"Current page — URL: {url} | Title: {title}{diagnostics}",
                    metadata={"action": action, "url": url, "title": title}
                )

            else:
                return SkillResult(
                    success=False,
                    error=(
                        f"Unsupported action: '{action}'. "
                        "Supported: screenshot, navigate, scroll, mouse_move, left_click, right_click, "
                        "middle_click, double_click, left_click_drag, type, key, cursor_position"
                    )
                )

        except Exception as e:
            logger.error(f"Computer use action '{action}' failed: {e}")
            return SkillResult(
                success=False,
                error=f"Error executing '{action}': {e}",
                metadata={"action": action}
            )

    async def __aenter__(self):
        await self._ensure_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()
