import pytest
from agents.plan_compiler import PlanCompiler

def test_plan_compiler_legacy_json():
    compiler = PlanCompiler()
    markdown = '{"task_id": "test_legacy", "goal": "legacy test"}'
    task_context = {}
    project_summary = {}
    
    result = compiler.compile(markdown, task_context, project_summary)
    assert result["ok"] is True
    assert result["plan_contract"]["task_id"] == "test_legacy"
    assert result["plan_contract"]["goal"] == "legacy test"

def test_plan_compiler_invalid_markdown():
    compiler = PlanCompiler()
    markdown = "Just some text without the header"
    
    result = compiler.compile(markdown, {}, {})
    assert result["ok"] is False
    assert result["plan_contract"] is None
    assert any(err["type"] == "PLANNER_FORMAT_ERROR" for err in result["errors"])

def test_plan_compiler_valid_markdown():
    compiler = PlanCompiler()
    markdown = """# PlannerMarkdownPlan

## Task Analysis
Test analysis

## Task Type
web

## Execution Route
CODE_WORKFLOW

## Agent Route Map
- Planner: step 1
- Generator: step 2

## User Visible Plan
1. Step A
2. Step B

## Files To Inspect
- package.json
- src/main.py

## Allowed Files
- src/App.tsx

## Forbidden Files
- .env

## Implementation Strategy
Use React.

## Implementation Steps
1. Inspect the existing app
2. Modify code

## Test Commands
```yaml
- name: build
  cmd: npm run build
  timeout_sec: 120
  required: true
```

## Dev Server
```yaml
enabled: false
```

## Smoke Tests
```yaml
- id: page_load
  type: browser
  action: goto
  target: http://localhost:3000
```

## Acceptance Criteria
- Passes build

## Verification Strategy
Runner will run build.

## External Research
```yaml
required: false
```

## Package JSON Policy
```yaml
allow_modify: false
```

## Repair Policy
```yaml
max_repair_rounds: 3
```

## Rollback Policy
```yaml
snapshot_before_patch: true
```

## Risks
- Unknown
"""
    task_context = {"task_id": "md_task_001", "user_request": "Build something"}
    project_summary = {}
    
    result = compiler.compile(markdown, task_context, project_summary)
    
    assert result["ok"] is True
    contract = result["plan_contract"]
    assert contract["task_id"] == "md_task_001"
    assert contract["goal"] == "Build something"
    assert contract["task_type"] == "web"
    assert contract["execution_route"] == "CODE_WORKFLOW"
    assert contract["problem_analysis"] == "Test analysis"
    assert len(contract["agent_route_map"]) == 2
    assert contract["agent_route_map"][0]["step"] == "Planner: step 1"
    
    assert len(contract["user_visible_plan"]) == 2
    assert contract["user_visible_plan"][0]["description"] == "1. Step A"
    
    assert "package.json" in contract["required_files_to_inspect"]
    assert "src/App.tsx" in contract["allowed_files"]
    assert ".env" in contract["forbidden_files"]
    
    assert contract["implementation_strategy"] == "Use React."
    
    assert len(contract["implementation_steps"]) == 2
    assert contract["implementation_steps"][0]["title"] == "Inspect the existing app"
    
    assert len(contract["test_commands"]) == 1
    assert contract["test_commands"][0]["name"] == "build"
    
    assert contract["dev_server"]["enabled"] is False
    
    assert len(contract["smoke_tests"]) == 1
    assert contract["smoke_tests"][0]["id"] == "page_load"
    
    assert contract["acceptance_criteria"] == ["Passes build"]
    assert contract["verification_strategy"] == "Runner will run build."
    
    assert contract["external_research"]["required"] is False
    assert contract["package_json_policy"]["allow_modify"] is False
    assert contract["repair_policy"]["max_repair_rounds"] == 3
    assert contract["rollback_policy"]["snapshot_before_patch"] is True
    assert contract["risks"] == ["Unknown"]
