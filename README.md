# OBS Code

OBS Code is a local coding workbench built around one Harness Orchestrator and five bounded agents. The UI keeps the main conversation user-facing and compact, while raw tool logs, model traces, screenshots, and runner artifacts stay in debug artifacts.

## Architecture

Every task enters through the Harness. Agents never call each other directly.

```text
UI / Desktop Shell
    -> FastAPI /chat/stream
    -> HarnessRuntime
    -> Planner -> PlanContract
    -> Search Gate -> Search, only when current external facts are needed
    -> Generator -> file changes limited to PlanContract.allowed_files
    -> Runner -> commands, dev servers, and browser smoke evidence
    -> Evaluator -> one EvalVerdict per round
    -> Harness decision -> next round or final answer
```

The five agent files are:

- `src/agents/planner_agent.py`
- `src/agents/search_agent.py`
- `src/agents/generator_agent.py`
- `src/agents/runner_agent.py`
- `src/agents/evaluator_agent.py`

Harness contracts, policy checks, mode mapping, Search Gate rules, and permission metadata live in `src/agents/harness_engine.py`. The state machine and SSE streaming loop live in `src/agents/harness_runtime.py`.

## Rules Implemented

- Planner only emits `PlanContract`.
- Search only runs after the Harness Search Gate allows it.
- Generator only reads and writes files allowed by `PlanContract.allowed_files`.
- Runner only executes approved commands, manages dev servers, performs browser smoke tests, and writes artifacts.
- Evaluator only judges evidence and emits one verdict for the current round.
- Temporary workflow output is kept under Harness-managed artifact/workspace locations, not the repository root.
- Legacy direct-execution layers, generated product endpoints, alternate comparison modes, and checked-in build output folders have been removed from the runtime architecture.

## UI

The frontend lives in `ui/` and follows the Harness timeline model:

- left thread list
- top runtime/context controls
- central timeline with status, current issue, next action, and round summary
- optional right preview/evidence pane
- bottom composer

The UI should summarize user-facing progress. Raw JSON, command logs, and stack traces belong in logs and debug artifacts.

## Run

Start the normal local stack:

```bash
./run.sh start
```

Direct backend:

```bash
PYTHONPATH=src uv run uvicorn api:app --host 0.0.0.0 --port 8000
```

PyCharm backend debugging:

```bash
python scripts/pycharm_debug_backend.py
```

That script starts the Vite frontend automatically, then runs the backend in the current Python process so breakpoints can enter FastAPI endpoints and Harness code.

Frontend only:

```bash
npm --prefix ui run dev
```

Build frontend:

```bash
npm --prefix ui run build
```

## Project Layout

```text
obs/
├── HARNESS_ORCHESTRATOR_SPEC.md
├── AGENTS.md
├── run.sh
├── scripts/
│   ├── pycharm_debug_backend.py
│   └── run_obs_code_100_prompt_checks.py
├── src/
│   ├── api.py
│   ├── desktop_app.py
│   ├── main.py
│   ├── agents/
│   │   ├── harness_engine.py
│   │   ├── harness_runtime.py
│   │   ├── planner_agent.py
│   │   ├── search_agent.py
│   │   ├── generator_agent.py
│   │   ├── runner_agent.py
│   │   └── evaluator_agent.py
│   ├── config/
│   ├── core/
│   ├── services/
│   ├── skills/
│   └── utils/
├── tests/
└── ui/
```

Runtime state is written under `logs/` and Harness artifacts under `.harness/`. Build outputs such as `ui/dist/`, `build/`, `dist/`, and packaged desktop artifacts are generated locally and are not source files.

## Test

Core checks:

```bash
PYTHONPATH=src python -m compileall -q src scripts
PYTHONPATH=src python -m pytest -q tests
npm --prefix ui run build
python scripts/run_obs_code_100_prompt_checks.py
```

The 100-prompt checklist is read from `~/Downloads/obs_code_assistant_100_test_prompts.md` and writes a report to `.harness/test_reports/obs_code_assistant_100_test_report.md`.
