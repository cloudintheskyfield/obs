# OBS Code Skill

## What This Service Is

OBS Code is a local AI workbench and Omni Agent API service. It combines chat, planning, tool execution, workspace browsing, skills management, logs, and architecture inspection in one runtime.

Base URL: `http://10.25.35.64:8000`

OpenAPI: `http://10.25.35.64:8000/openapi.json`

## When To Use

Use this service when you need an agent runtime that can:

- stream chat responses
- inspect and execute installed skills
- browse and switch workspaces
- manage thread context and session state
- inspect runtime metadata and architecture

## Key Endpoints

- `GET /health`
  Returns service health.
- `GET /runtime`
  Returns model, workspace, and runtime capabilities.
- `GET /skills`
  Returns executable tool schemas.
- `GET /skill-catalog`
  Returns the skill catalog shown in the UI.
- `POST /execute`
  Executes a named tool with parameters.
- `POST /chat/stream`
  Starts a streaming agent response.
- `GET /workspace`
  Returns the current workspace.
- `POST /workspace`
  Updates the current workspace path.
- `GET /architecture`
  Returns runtime architecture metadata.

## Suggested Flow

1. Call `GET /health` or `GET /runtime` to confirm the service is alive.
2. Call `GET /skills` or `GET /skill-catalog` to inspect available abilities.
3. If needed, update the workspace before execution.
4. Use `POST /chat/stream` for full agent interactions, or `POST /execute` for direct tool calls.

## Notes

- This service is API-first and UI-backed; the root path serves the web console.
- The canonical machine-readable spec is `openapi.json`.
- If you need current skill inventory or workspace details, prefer live API reads over assumptions.
