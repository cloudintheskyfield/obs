import re
import yaml
from typing import Dict, Any, List, Optional
from loguru import logger

class PlanCompiler:
    """
    Compiles a PlannerMarkdownPlan into a strict PlanContract JSON format.
    """

    def __init__(self):
        self.default_protected_files = [
            ".env", ".env.*", ".git/**", "node_modules/**", "dist/**", "build/**",
            ".harness/**", "logs/**", "screenshots/**", "workflow_*/**",
            "workflow_game_tests/**", "package-lock.json", "pnpm-lock.yaml",
            "yarn.lock", "poetry.lock", "Pipfile.lock", "Cargo.lock", "go.sum"
        ]

    def compile(self, markdown: str, task_context: Dict[str, Any], project_summary: Dict[str, Any]) -> Dict[str, Any]:
        """
        Takes raw markdown from Planner and compiles it into a PlanContract.
        Returns a result object:
        {
            "ok": bool,
            "plan_contract": dict | None,
            "errors": list,
            "warnings": list
        }
        """
        # If it looks like legacy JSON, try parsing it directly.
        md_stripped = markdown.strip()
        if md_stripped.startswith("{") and not md_stripped.startswith("# PlannerMarkdownPlan"):
            try:
                import json
                contract = json.loads(md_stripped)
                return {
                    "ok": True,
                    "plan_contract": contract,
                    "errors": [],
                    "warnings": []
                }
            except Exception as e:
                pass # Fall through to markdown parsing if JSON parsing fails, though it shouldn't happen.

        if "# PlannerMarkdownPlan" not in markdown:
            return {
                "ok": False,
                "plan_contract": None,
                "errors": [{"type": "PLANNER_FORMAT_ERROR", "message": "Planner did not output a valid PlannerMarkdownPlan."}],
                "warnings": []
            }

        sections = self._extract_sections(markdown)
        errors = []
        warnings = []
        
        # Helper to get section
        def get_section(name: str, default=""):
            # Try exact match or case-insensitive match
            for k, v in sections.items():
                if k.lower() == name.lower():
                    if v.strip().lower() == "none":
                        return default
                    return v.strip()
            return default

        # Helper to parse lists
        def parse_list(name: str) -> List[str]:
            content = get_section(name)
            if not content:
                return []
            lines = [line.strip() for line in content.split("\n")]
            result = []
            for line in lines:
                if line.startswith("- "):
                    result.append(line[2:].strip())
                elif line.startswith("* "):
                    result.append(line[2:].strip())
            return result
        
        # Helper to parse YAML
        def parse_yaml(name: str, default: Any = None) -> Any:
            content = get_section(name)
            if not content:
                return default if default is not None else {}
            try:
                # Strip markdown code blocks if any
                content = re.sub(r"^```yaml\n", "", content)
                content = re.sub(r"\n```$", "", content)
                content = re.sub(r"^```\n", "", content)
                parsed = yaml.safe_load(content)
                return parsed if parsed is not None else (default if default is not None else {})
            except Exception as e:
                warnings.append({"type": "YAML_PARSE_ERROR", "section": name, "message": str(e)})
                return default if default is not None else {}

        # Parse sections
        problem_analysis = get_section("Task Analysis")
        task_type = get_section("Task Type", "code")
        execution_route = get_section("Execution Route", "CODE_WORKFLOW")
        
        agent_route_map_raw = parse_list("Agent Route Map")
        agent_route_map = [{"step": item} for item in agent_route_map_raw]
        
        user_visible_plan_raw = get_section("User Visible Plan")
        user_visible_plan = []
        for line in user_visible_plan_raw.split("\n"):
            line = line.strip()
            if re.match(r"^\d+\.", line):
                user_visible_plan.append({"description": line})
        
        required_files_to_inspect = parse_list("Files To Inspect")
        allowed_files = parse_list("Allowed Files")
        forbidden_files = parse_list("Forbidden Files") or self.default_protected_files
        
        implementation_strategy = get_section("Implementation Strategy")
        
        # Implementation Steps
        impl_steps_raw = get_section("Implementation Steps")
        implementation_steps = []
        for i, line in enumerate(impl_steps_raw.split("\n")):
            line = line.strip()
            if re.match(r"^\d+\.", line):
                desc = re.sub(r"^\d+\.\s*", "", line).strip()
                implementation_steps.append({
                    "id": f"S{i+1}",
                    "title": desc,
                    "description": desc,
                    "expected_output": ""
                })
        
        test_commands = parse_yaml("Test Commands", [])
        if not isinstance(test_commands, list):
            test_commands = []
            
        dev_server = parse_yaml("Dev Server", {
            "enabled": False,
            "start_cmd": "",
            "url": "",
            "ready_patterns": [],
            "timeout_sec": 60
        })
        
        smoke_tests = parse_yaml("Smoke Tests", [])
        if not isinstance(smoke_tests, list):
            smoke_tests = []
            
        acceptance_criteria = parse_list("Acceptance Criteria")
        verification_strategy = get_section("Verification Strategy")
        
        external_research = parse_yaml("External Research", {
            "required": False,
            "reason": "",
            "queries": [],
            "allowed_domains": [],
            "max_results": 5,
            "max_pages_to_scrape": 3,
            "freshness": "stable",
            "search_agent_required": False
        })
        
        package_json_policy = parse_yaml("Package JSON Policy", {
            "allow_modify": False,
            "allow_add_scripts": False,
            "allow_add_dependencies": False,
            "requires_approval": True
        })
        
        repair_policy = parse_yaml("Repair Policy", {
            "max_repair_rounds": 3,
            "repair_scope": "minimal_patch",
            "do_not_rewrite_whole_project": True,
            "if_same_error_repeats": "REPLAN"
        })
        
        rollback_policy = parse_yaml("Rollback Policy", {
            "snapshot_before_patch": True,
            "rollback_on_invalid_patch": True,
            "preserve_harness_artifacts": True
        })
        
        risks = parse_list("Risks")

        # Compile final contract
        plan_contract = {
            "schema_version": "1.0",
            "task_id": task_context.get("task_id", "task_001"),
            "goal": task_context.get("user_request", "Complete the user request"),
            "task_type": task_type,
            "execution_route": execution_route,
            "problem_analysis": problem_analysis,
            "non_goals": [],
            "assumptions": [],
            "agent_route_map": agent_route_map,
            "user_visible_plan": user_visible_plan,
            "implementation_strategy": implementation_strategy,
            "allowed_files": allowed_files,
            "forbidden_files": forbidden_files,
            "required_files_to_inspect": required_files_to_inspect,
            "implementation_steps": implementation_steps,
            "test_commands": test_commands,
            "dev_server": dev_server,
            "smoke_tests": smoke_tests,
            "acceptance_criteria": acceptance_criteria,
            "verification_strategy": verification_strategy,
            "repair_policy": repair_policy,
            "rollback_policy": rollback_policy,
            "external_research": external_research,
            "package_json_policy": package_json_policy,
            "risks": risks
        }

        # Check required sections loosely
        if not implementation_steps:
            errors.append({
                "type": "MISSING_SECTION",
                "section": "Implementation Steps",
                "message": "PlannerMarkdownPlan is missing or failed to parse Implementation Steps."
            })
            
        # We can enforce other critical sections if needed, but the compiler should be robust.
        
        if errors:
            return {
                "ok": False,
                "plan_contract": None,
                "errors": errors,
                "warnings": warnings
            }

        return {
            "ok": True,
            "plan_contract": plan_contract,
            "errors": errors,
            "warnings": warnings
        }

    def _extract_sections(self, markdown: str) -> Dict[str, str]:
        """
        Splits markdown by '## ' headers and returns a dictionary mapping header name to content.
        """
        sections = {}
        current_header = None
        current_content = []
        
        for line in markdown.split("\n"):
            if line.startswith("## "):
                # Save previous section
                if current_header:
                    sections[current_header] = "\n".join(current_content).strip()
                
                # Start new section
                current_header = line[3:].strip()
                current_content = []
            elif current_header:
                current_content.append(line)
                
        # Save the last section
        if current_header:
            sections[current_header] = "\n".join(current_content).strip()
            
        return sections
