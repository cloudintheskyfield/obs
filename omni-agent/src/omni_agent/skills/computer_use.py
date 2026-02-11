"""Computer Use Skill - Claude官方计算机使用技能"""
import base64
import io
from typing import Optional, Dict, Any, Tuple
from pathlib import Path

try:
    from PIL import Image, ImageDraw
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    Image = None
    ImageDraw = None

try:
    from playwright.async_api import async_playwright, Page, Browser
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None
    Page = None
    Browser = None

from loguru import logger

from .base_skill import BaseSkill, SkillResult


class ComputerUseSkill(BaseSkill):
    """Computer Use Skill - 模拟Claude的计算机使用能力"""
    
    def __init__(self, screenshot_dir: str = "screenshots"):
        super().__init__(
            name="computer_use",
            description="Take screenshots, click, type, and interact with the computer screen"
        )
        
        self.screenshot_dir = Path(screenshot_dir)
        self.screenshot_dir.mkdir(exist_ok=True)
        
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
        self.playwright = None
        
        # 定义参数
        self.add_parameter("action", "str", "Action to perform: screenshot, click, type, scroll", True)
        self.add_parameter("coordinate", "list", "Coordinates [x, y] for click actions", False)
        self.add_parameter("text", "str", "Text to type", False)
        self.add_parameter("scroll_direction", "str", "Scroll direction: up, down, left, right", False, "down")
        self.add_parameter("scroll_amount", "int", "Number of scroll steps", False, 3)
    
    async def initialize(self):
        """初始化浏览器"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.warning("Playwright not available - Computer Use Skill disabled")
            self.enabled = False
            return
            
        if not self.playwright:
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor'
                ]
            )
            
            self.page = await self.browser.new_page()
            await self.page.set_viewport_size({"width": 1280, "height": 720})
            
            logger.info("Computer Use Skill initialized")
    
    async def cleanup(self):
        """清理资源"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        
        self.browser = None
        self.page = None
        self.playwright = None
        
        logger.info("Computer Use Skill cleaned up")
    
    async def take_screenshot(self) -> str:
        """截取屏幕截图"""
        if not self.page:
            await self.initialize()
        
        screenshot_path = self.screenshot_dir / f"screenshot_{self._get_timestamp()}.png"
        await self.page.screenshot(path=str(screenshot_path), full_page=True)
        
        # 转换为base64
        with open(screenshot_path, "rb") as f:
            image_data = f.read()
            base64_image = base64.b64encode(image_data).decode('utf-8')
        
        logger.info(f"Screenshot saved: {screenshot_path}")
        return base64_image
    
    async def click(self, coordinate: Tuple[int, int]) -> str:
        """点击指定坐标"""
        if not self.page:
            await self.initialize()
        
        x, y = coordinate
        await self.page.mouse.click(x, y)
        
        # 等待页面响应
        await self.page.wait_for_timeout(500)
        
        # 截图记录结果
        screenshot = await self.take_screenshot()
        
        logger.info(f"Clicked at coordinate ({x}, {y})")
        return screenshot
    
    async def type_text(self, text: str) -> str:
        """输入文本"""
        if not self.page:
            await self.initialize()
        
        await self.page.keyboard.type(text)
        await self.page.wait_for_timeout(500)
        
        # 截图记录结果
        screenshot = await self.take_screenshot()
        
        logger.info(f"Typed text: {text}")
        return screenshot
    
    async def scroll(self, direction: str = "down", amount: int = 3) -> str:
        """滚动页面"""
        if not self.page:
            await self.initialize()
        
        delta_map = {
            "up": (0, -120 * amount),
            "down": (0, 120 * amount),
            "left": (-120 * amount, 0),
            "right": (120 * amount, 0)
        }
        
        if direction not in delta_map:
            raise ValueError(f"Invalid scroll direction: {direction}")
        
        delta_x, delta_y = delta_map[direction]
        await self.page.mouse.wheel(delta_x, delta_y)
        await self.page.wait_for_timeout(500)
        
        # 截图记录结果
        screenshot = await self.take_screenshot()
        
        logger.info(f"Scrolled {direction} by {amount} steps")
        return screenshot
    
    async def navigate_to(self, url: str) -> str:
        """导航到URL"""
        if not self.page:
            await self.initialize()
        
        await self.page.goto(url, wait_until="networkidle")
        await self.page.wait_for_timeout(1000)
        
        # 截图记录结果
        screenshot = await self.take_screenshot()
        
        logger.info(f"Navigated to: {url}")
        return screenshot
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    
    def _create_annotated_screenshot(
        self, 
        base64_image: str, 
        coordinate: Optional[Tuple[int, int]] = None
    ) -> str:
        """创建带标注的截图"""
        if not PIL_AVAILABLE:
            logger.warning("PIL not available - returning original image")
            return base64_image
            
        try:
            # 解码base64图像
            image_data = base64.b64decode(base64_image)
            image = Image.open(io.BytesIO(image_data))
            
            if coordinate:
                # 在图像上标注点击位置
                draw = ImageDraw.Draw(image)
                x, y = coordinate
                radius = 10
                
                # 画红色圆圈
                draw.ellipse(
                    [x - radius, y - radius, x + radius, y + radius],
                    outline="red",
                    width=3
                )
                
                # 画十字线
                draw.line([x - radius * 2, y, x + radius * 2, y], fill="red", width=2)
                draw.line([x, y - radius * 2, x, y + radius * 2], fill="red", width=2)
            
            # 转换回base64
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            buffer.seek(0)
            
            annotated_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
            return annotated_base64
            
        except Exception as e:
            logger.error(f"Error creating annotated screenshot: {e}")
            return base64_image
    
    async def execute(self, **kwargs) -> SkillResult:
        """执行Computer Use操作"""
        action = kwargs.get("action")
        
        try:
            if action == "screenshot":
                screenshot = await self.take_screenshot()
                return SkillResult(
                    success=True,
                    base64_image=screenshot,
                    content="Screenshot taken successfully",
                    metadata={"action": action}
                )
            
            elif action == "click":
                coordinate = kwargs.get("coordinate")
                if not coordinate or len(coordinate) != 2:
                    return SkillResult(
                        success=False,
                        error="Click action requires coordinate parameter [x, y]"
                    )
                
                screenshot = await self.click(tuple(coordinate))
                
                # 创建带标注的截图
                annotated_screenshot = self._create_annotated_screenshot(
                    screenshot, tuple(coordinate)
                )
                
                return SkillResult(
                    success=True,
                    base64_image=annotated_screenshot,
                    content=f"Clicked at coordinate {coordinate}",
                    metadata={
                        "action": action,
                        "coordinate": coordinate
                    }
                )
            
            elif action == "type":
                text = kwargs.get("text")
                if not text:
                    return SkillResult(
                        success=False,
                        error="Type action requires text parameter"
                    )
                
                screenshot = await self.type_text(text)
                return SkillResult(
                    success=True,
                    base64_image=screenshot,
                    content=f"Typed text: '{text}'",
                    metadata={
                        "action": action,
                        "text": text
                    }
                )
            
            elif action == "scroll":
                direction = kwargs.get("scroll_direction", "down")
                amount = kwargs.get("scroll_amount", 3)
                
                screenshot = await self.scroll(direction, amount)
                return SkillResult(
                    success=True,
                    base64_image=screenshot,
                    content=f"Scrolled {direction} by {amount} steps",
                    metadata={
                        "action": action,
                        "direction": direction,
                        "amount": amount
                    }
                )
            
            elif action == "navigate":
                url = kwargs.get("url")
                if not url:
                    return SkillResult(
                        success=False,
                        error="Navigate action requires url parameter"
                    )
                
                screenshot = await self.navigate_to(url)
                return SkillResult(
                    success=True,
                    base64_image=screenshot,
                    content=f"Navigated to: {url}",
                    metadata={
                        "action": action,
                        "url": url
                    }
                )
            
            else:
                return SkillResult(
                    success=False,
                    error=f"Unsupported action: {action}. Supported actions: screenshot, click, type, scroll, navigate"
                )
        
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Error executing {action}: {str(e)}",
                metadata={"action": action}
            )
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        await self.initialize()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.cleanup()