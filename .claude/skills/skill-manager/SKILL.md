---
name: skill-manager
description: Manage OBS agent skills — search store, install, delete, reload, and list
protected: true
---

# Skill Manager

Use this skill to manage all OBS agent skills at runtime — no bash/curl needed.

## IMPORTANT: Skill Installation Workflow

**When the user asks you to install or use a skill you don't have:**

1. **Search the store first**
   ```
   skill_manager command="search_store" query="<what user wants>"
   ```
2. **If found in store** → install it immediately
   ```
   skill_manager command="install_store" name="<name>"
   ```
3. **If found via URL** → install from URL
   ```
   skill_manager command="install_url" url="<url>"
   ```
4. **If nothing found** → build the skill yourself using `install_md`

Always search before building. Never assume a skill doesn't exist without checking.

---

## Commands

### Search the skill store
```
skill_manager command="search_store" query="timer"
skill_manager command="search_store" query="翻译"
skill_manager command="search_store" query="docker"
```
Returns matching skills with descriptions, tags, and install commands.
Add `include_github=true` to also search GitHub repos tagged `obs-code-skill`.

### Install from store (by name)
```
skill_manager command="install_store" name="translator"
skill_manager command="install_store" name="pomodoro"
```
Fetches the skill from the built-in registry and installs it instantly.

### Install from URL
```
skill_manager command="install_url" url="http://127.0.0.1:8001/skill.md"
```
Fetches the SKILL.md from the URL (handles 127.0.0.1 → host rewriting automatically) and installs it.
Optional: `name="my-skill"` to override auto-detected name.

### Install from content (build your own)
```
skill_manager command="install_md" name="my-skill" skill_md="---\nname: my-skill\ndescription: ...\n---\n\n# Instructions"
```
Use this when the skill store has no match — write your own SKILL.md and install it.

### List all installed skills
```
skill_manager command="list"
```
Returns each skill's name, description, install time, tools, and protected status.

### Delete a skill
```
skill_manager command="delete" name="weather"
```
Protected skills (like `skill-manager` itself) cannot be deleted.

### Reload all skills from disk
```
skill_manager command="reload"
```
Hot-reloads without server restart.

### Get skill info
```
skill_manager command="info" name="terminal"
```

---

## Built-in Store Skills

The store currently includes these ready-to-install skills:

| Name | Description |
|------|-------------|
| `translator` | Translate text between Chinese, English, Japanese, etc. |
| `pomodoro` | 25-min focus timer via bash |
| `system-monitor` | CPU / memory / disk / process monitor |
| `ip-lookup` | IP geolocation and network info |
| `uuid-gen` | UUID v4, random tokens, secure passwords |
| `json-tools` | Format, validate, query JSON data |
| `git-assistant` | Common git workflows via bash |
| `docker-helper` | Docker container/image management |
| `countdown` | Live countdown timer |
| `http-tester` | Test HTTP endpoints with curl |

---

## Notes
- `skill-manager` is a **protected system skill** — it cannot be deleted.
- Newly installed skills appear instantly in the Skills panel (real-time SSE sync).
- Use `install_url` instead of bash curl for any URL-based install — it handles Docker host networking automatically.
- Skills installed from the store are definition-only (instruction-based) — they guide you on how to use existing tools like bash, web_search, etc.
