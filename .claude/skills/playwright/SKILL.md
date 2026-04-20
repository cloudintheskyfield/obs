---
name: playwright
description: 在隔离 Docker 容器中运行 Playwright 自动化测试和爬虫
tools: code-sandbox
---

# Playwright Skill

在隔离的 Docker 容器中安全执行 Playwright 自动化测试和网页爬虫。

## 功能特性

- **安全隔离**: Playwright 代码在独立 Docker 容器中运行
- **多浏览器支持**: Chromium, Firefox, WebKit
- **自动化测试**: 网页交互、截图、表单填写
- **网页爬虫**: 抓取动态网页内容

## 使用方法

### Python + Playwright

```python
result = await execute_skill("code_sandbox",
    language="python",
    code='''
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    print(page.title())
    browser.close()
''',
    timeout=60
)
```

### JavaScript + Playwright

```python
result = await execute_skill("code_sandbox",
    language="javascript",
    code='''
const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('https://example.com');
  console.log(await page.title());
  await browser.close();
})();
''',
    timeout=60
)
```

## 参数说明

- `language`: 编程语言 (python/javascript)
- `code`: 要执行的 Playwright 代码
- `timeout`: 超时时间（秒），默认 60s

## 返回值

```python
{
    "success": True,
    "stdout": "程序标准输出",
    "stderr": "错误输出",
    "exit_code": 0,
    "execution_time": 1.23
}
```

## 最佳实践

1. 设置合理的超时时间（建议 60s 以上）
2. 检查 exit_code 确认执行成功
3. 处理 stderr 中的错误信息
4. 使用 try-finally 确保浏览器关闭

## 示例场景

### 网页截图

```python
code='''
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    page.screenshot(path="screenshot.png")
    print("Screenshot saved")
    browser.close()
'''
```

### 表单填写

```python
code='''
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com/form")
    page.fill("#username", "testuser")
    page.fill("#password", "password123")
    page.click("button[type=submit]")
    print(page.url)
    browser.close()
'''
```

### 等待元素

```python
code='''
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    page.goto("https://example.com")
    page.wait_for_selector(".content")
    print(page.text_content(".content"))
    browser.close()
'''
```
