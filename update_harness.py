import re
from pathlib import Path

path = Path('src/agents/harness_runtime.py')
content = path.read_text()

# We need to replace:
# plan_contract = planner.last_plan_contract
# if not plan_contract.get("task_id"):
#     plan_contract["task_id"] = provisional_task_id
# self.harness_engine.validate_schema(plan_contract, "PlanContract")
# self._write_json_file(workspace, ".harness/plan.json", plan_contract)
# self._write_json_file(workspace, f".harness/runs/run_{round_id:03d}/output/plan_contract.json", plan_contract)
# 
# Wait, some places use run_001 instead of {round_id:03d}.

replacement = """
                        plan_contract = planner.last_plan_contract
                        if not plan_contract.get("task_id"):
                            plan_contract["task_id"] = provisional_task_id
                        
                        # Save compiler artifacts
                        round_str = f"{round_id:03d}" if 'round_id' in locals() else "001"
                        self._write_text_file(workspace, f".harness/plans/plan_{round_str}.md", planner.last_plan_markdown)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.contract.json", plan_contract)
                        self._write_json_file(workspace, f".harness/plans/plan_{round_str}.compiler_report.json", planner.last_compiler_report)
                        
                        if not planner.last_compiler_report.get("ok", True):
                            yield self._sse(
                                {
                                    "type": "harness_decision",
                                    "decision": {
                                        "decision": "PLAN_COMPILER_ERROR",
                                        "reason": "Planner failed to produce valid markdown plan",
                                        "next_agent": "",
                                        "next_state": "TERMINAL_ERROR"
                                    },
                                }
                            )
                            return
                        
                        self.harness_engine.validate_schema(plan_contract, "PlanContract")
                        self._write_json_file(workspace, ".harness/plan.json", plan_contract)
                        run_out_path = f".harness/runs/run_{round_id:03d}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
                        self._write_json_file(workspace, run_out_path, plan_contract)
"""

def replacer(match):
    indent = match.group(1)
    
    # We replace the whole block
    block = f"""{indent}plan_contract = planner.last_plan_contract
{indent}if not plan_contract.get("task_id"):
{indent}    plan_contract["task_id"] = provisional_task_id
{indent}
{indent}round_str = f"{{round_id:03d}}" if 'round_id' in locals() else "001"
{indent}run_out_path = f".harness/runs/run_{{round_id:03d}}/output/plan_contract.json" if 'round_id' in locals() else ".harness/runs/run_001/output/plan_contract.json"
{indent}
{indent}self._write_text_file(workspace, f".harness/plans/plan_{{round_str}}.md", planner.last_plan_markdown)
{indent}self._write_json_file(workspace, f".harness/plans/plan_{{round_str}}.contract.json", plan_contract)
{indent}self._write_json_file(workspace, f".harness/plans/plan_{{round_str}}.compiler_report.json", planner.last_compiler_report)
{indent}
{indent}if not planner.last_compiler_report.get("ok", True):
{indent}    yield self._sse(
{indent}        {{
{indent}            "type": "harness_decision",
{indent}            "decision": {{
{indent}                "decision": "PLAN_COMPILER_ERROR",
{indent}                "reason": "Planner failed to produce valid markdown plan",
{indent}                "next_agent": "",
{indent}                "next_state": "TERMINAL_ERROR"
{indent}            }}
{indent}        }}
{indent}    )
{indent}    return
{indent}
{indent}self.harness_engine.validate_schema(plan_contract, "PlanContract")
{indent}self._write_json_file(workspace, ".harness/plan.json", plan_contract)
{indent}self._write_json_file(workspace, run_out_path, plan_contract)"""
    return block

pattern = r"( +)plan_contract = planner\.last_plan_contract\n\1if not plan_contract\.get\(\"task_id\"\):\n\1    plan_contract\[\"task_id\"\] = provisional_task_id\n\1self\.harness_engine\.validate_schema\(plan_contract, \"PlanContract\"\)\n\1self\._write_json_file\(workspace, \"\.harness/plan\.json\", plan_contract\)\n\1self\._write_json_file\(workspace,.*?plan_contract\.json\", plan_contract\)"

new_content, count = re.subn(pattern, replacer, content)

print(f"Replaced {count} occurrences.")
if count > 0:
    path.write_text(new_content)

