# AGENTS.md

## Harness Rules

- All agent inputs and outputs must pass through the Harness Orchestrator.
- Agents must not call each other directly.
- Planner only plans and outputs `PlanContract`.
- Search only researches external sources after the Harness Search Gate allows it.
- Generator only modifies files allowed by `PlanContract.allowed_files`.
- Runner only executes commands and browser smoke tests, and only writes artifacts.
- Evaluator only judges evidence and outputs one `EvalVerdict` per round.
- Raw tool logs belong in debug artifacts; the main UI should show user-facing summaries.
- Use only the skills named in `HARNESS_ORCHESTRATOR_SPEC.md`, with existing local wrappers treated only as implementation bindings for those roles.
- Do not crawl or import the full FindSkills directory; query FindSkills only for the allowlisted skill names when lookup is needed.

## Coding Rules

- Prefer the smallest runnable implementation that satisfies the task.
- Do not introduce dependencies unless the plan explicitly allows it.
- Do not modify `.env`, `.git`, `node_modules`, `dist`, `build`, or `.harness/state.json`.
- Repairs should be minimal and evidence-driven.

## Testing Rules

- Frontend projects must run a build check when available.
- Web projects must include a page-load smoke test.
- Game projects must test the start action and at least one real control input.
- Runner script errors default to Harness/Runner infrastructure, not product code.
