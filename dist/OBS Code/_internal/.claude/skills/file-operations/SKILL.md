---
name: file-operations
description: View, create, edit, and manage text files in the workspace
---

# File Operations Skill

A powerful text editor for viewing, creating, and editing files. All edits are made to file contents only and are not executed as code.

## Quick Start

View a file:

```python
result = await execute_skill("str_replace_editor", command="view", path="src/main.py")
```

Create a new file:

```python
result = await execute_skill("str_replace_editor", 
    command="create",
    path="new_file.py",
    file_text="print('Hello World')"
)
```

Replace text in a file:

```python
result = await execute_skill("str_replace_editor",
    command="str_replace",
    path="src/main.py",
    old_str="old_function_name",
    new_str="new_function_name"
)
```

## Available Commands

### view
View file contents with line numbers
- **path**: File path relative to workspace (required)
- **view_range**: Optional `[start_line, end_line]` to view specific range
- **Returns**: File contents with line numbers

### create
Create a new file with content
- **path**: File path relative to workspace (required)
- **file_text**: Complete file content (required)
- **Returns**: Success confirmation with file path

### str_replace
Replace exact string match in file
- **path**: File path (required)
- **old_str**: Exact string to find (required)
- **new_str**: Replacement string (required)
- **Returns**: Confirmation of replacement with context

### insert
Insert text after specific line number
- **path**: File path (required)
- **insert_line**: Line number to insert after (required)
- **new_str**: Text to insert (required)
- **Returns**: Confirmation with updated content

### undo_edit
Undo the last edit operation
- **path**: File path (required)
- **Returns**: Restored content

## Supported File Types

Text files with these extensions:
- **Code**: `.py`, `.js`, `.ts`, `.go`, `.rs`, `.java`, `.c`, `.cpp`, `.rb`, `.php`
- **Markup**: `.html`, `.xml`, `.md`, `.txt`
- **Config**: `.json`, `.yaml`, `.yml`, `.toml`, `.ini`, `.cfg`
- **Scripts**: `.sh`, `.bat`, `.ps1`, `.sql`, `.dockerfile`
- **Data**: `.csv`, `.log`

## Workflows

### Code Refactoring
1. View file to understand structure
2. Use `str_replace` to rename functions/variables
3. Verify changes with view command
4. If mistake, use `undo_edit`

### Multi-file Updates
1. View first file
2. Make replacement
3. View next file
4. Repeat replacements
5. Verify all changes

### Creating New Components
1. Use `create` with full content
2. View to verify
3. Make adjustments with `str_replace` if needed

## Best Practices

- **View before edit**: Always view file first to understand context
- **Exact matches**: `str_replace` requires exact string match including whitespace
- **Unique strings**: Choose `old_str` that appears only once, or edit will fail
- **Line-by-line for complex edits**: For major changes, use multiple `str_replace` or recreate file
- **Verify after edit**: View file after changes to confirm success
- **Use undo**: If edit doesn't work as expected, undo and try again

## Security

- **Workspace isolation**: All paths are relative to workspace directory
- **Path validation**: Cannot access files outside workspace (.. paths blocked)
- **Extension whitelist**: Only allowed file extensions can be edited
- **No execution**: This skill only edits files, never executes code
- **Backup**: Previous version available via `undo_edit`

## Error Handling

- **File not found**: Create file first with `create` command
- **Path outside workspace**: Use relative paths only
- **String not found**: Verify exact match including spaces/tabs
- **Multiple matches**: Make `old_str` more specific with surrounding context
- **Permission denied**: Check file permissions in workspace

## Examples

See `examples/` directory for:
- Refactoring code across multiple files
- Configuration file updates
- Template generation
- Batch text replacements
