---
name: computer-use
description: Use a mouse and keyboard to interact with a computer, take screenshots, and browse the web visually
---

# Computer Use Skill

Use this skill to interact with a computer through visual interface - take screenshots, move mouse, click, type text, and navigate web pages like a human would.

## Quick Start

Take a screenshot to see the current screen:

```python
result = await execute_skill("computer", action="screenshot")
```

Click at coordinates (100, 200):

```python
result = await execute_skill("computer", action="left_click", coordinate=[100, 200])
```

Type text:

```python
result = await execute_skill("computer", action="type", text="Hello World")
```

## Available Actions

### Screenshot
- **action**: `screenshot`
- **Returns**: Base64-encoded PNG image of the current screen
- **Use case**: See what's on screen, verify page loaded, check UI state

### Mouse Actions
- **mouse_move**: Move cursor to coordinate `[x, y]`
- **left_click**: Click left button at `[x, y]`
- **right_click**: Click right button at `[x, y]`
- **middle_click**: Click middle button at `[x, y]`
- **double_click**: Double-click at `[x, y]`
- **left_click_drag**: Drag from `[x1, y1]` to `[x2, y2]`

### Keyboard Actions
- **type**: Type text string (use `text` parameter)
- **key**: Press special key (use `text` parameter with key name like "Return", "Tab", "Escape")
- **cursor_position**: Get current cursor position

## Workflows

### Web Navigation Workflow
1. Take screenshot to see page
2. Identify element position visually
3. Click on element
4. Wait and take screenshot to verify
5. Continue interaction

### Form Filling Workflow
1. Screenshot to locate form fields
2. Click on first field
3. Type text
4. Press Tab to move to next field
5. Repeat until form complete
6. Click submit button

## Best Practices

- **Always screenshot first**: Before clicking, take a screenshot to understand the current state
- **Verify actions**: After important actions (navigation, form submit), take another screenshot to verify success
- **Use precise coordinates**: Coordinates are in pixels from top-left (0, 0)
- **Wait for page loads**: Some actions need time - if screenshot shows loading state, wait and retry
- **Handle popups**: Check screenshots for unexpected popups or dialogs

## Error Handling

- **Playwright not available**: Skill will be disabled if playwright is not installed
- **Invalid coordinates**: Ensure coordinates are within screen bounds
- **Browser not initialized**: Call will automatically initialize browser on first use
- **Screenshot failures**: Retry after short delay if screenshot returns empty

## Examples

See `examples/` directory for:
- Web scraping with visual navigation
- Form automation
- UI testing scenarios
- Multi-step workflows
