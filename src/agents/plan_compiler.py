import json
import re
from typing import Dict, Any, List, Optional, AsyncGenerator
from loguru import logger

from .base_agent import BaseAgent


class PlanCompiler(BaseAgent):
    """
    Compiles a PlannerMarkdownPlan into a strict PlanContract JSON format using an LLM.
    """

    def __init__(self, vllm_client: Any, skill_manager: Any = None) -> None:
        super().__init__("planner_compiler", vllm_client, skill_manager)

    async def compile(
        self,
        markdown: str,
        task_context: Dict[str, Any],
        project_summary: Dict[str, Any],
        model: str,
        session_id: str = "",
        previous_failures: Optional[List[Any]] = None,
        search_reports: Optional[List[Any]] = None,
    ) -> AsyncGenerator[Any, None]:
        """
        Takes raw markdown from Planner and compiles it into a PlanContract using the LLM.
        Yields SSE string chunks directly.
        The final yielded item is the compile_result dict:
        {
            "ok": bool,
            "plan_contract": dict | None,
            "errors": list,
            "warnings": list
        }
        """
        # If it looks like legacy JSON, try parsing it directly as a quick fallback.
        md_stripped = markdown.strip()
        if md_stripped.startswith("{") and not md_stripped.startswith("# PlannerMarkdownPlan"):
            try:
                contract = json.loads(md_stripped)
                yield {
                    "ok": True,
                    "plan_contract": contract,
                    "errors": [],
                    "warnings": []
                }
                return
            except Exception:
                pass

        if "# PlannerMarkdownPlan" not in markdown:
            yield {
                "ok": False,
                "plan_contract": None,
                "errors": [{"type": "PLANNER_FORMAT_ERROR", "message": "Planner did not output a valid PlannerMarkdownPlan."}],
                "warnings": []
            }
            return

        payload = {
            "schema_version": "1.0",
            "task_id": task_context.get("task_id", ""),
            "planner_markdown": markdown,
            "task_context": task_context,
            "project_summary": project_summary,
            "previous_failures": previous_failures or [],
            "search_reports": search_reports or [],
            "harness_defaults": {}
        }

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False, indent=2)},
        ]

        # 动态更新前端展示的状态
        yield self._status(
            "running",
            role="PlanCompiler",
            title="编译 PlanContract",
            detail="正在将 Markdown 计划转换为 JSON 结构化合约...",
            session_id=session_id
        )

        raw_content = ""
        chunk_count = 0
        try:
            stream = await self.vllm_client.chat_completion(
                messages=messages,
                tools=None,
                temperature=0.1,
                max_tokens=4000,
                stream=True,
                model=model,
            )
            
            async for chunk in stream:
                chunk_count += 1
                if isinstance(chunk, dict) and "__obs_phase" in chunk:
                    continue
                if "choices" not in chunk or not chunk["choices"]:
                    continue
                piece = chunk["choices"][0].get("delta", {}).get("content") or ""
                if piece:
                    raw_content += piece
                    yield self._sse(
                        {
                            "type": "agent_thinking",
                            "agent": "planner_compiler",
                            "delta": piece,
                            "session_id": session_id,
                        }
                    )
                    
                    if chunk_count % 15 == 0:
                        thinking_match = re.search(r"<think>([\s\S]*?)(?:</think>|$)", raw_content, re.IGNORECASE)
                        if thinking_match:
                            dynamic_detail = self._extract_thinking_summary(thinking_match.group(1), default_detail="解析和补全属性...")
                            yield self._status("running", role="PlanCompiler", title="编译 PlanContract", detail=dynamic_detail, session_id=session_id)

            contract = self._find_first_json_object(raw_content)

            if not contract:
                yield {
                    "ok": False,
                    "plan_contract": None,
                    "errors": [{"type": "COMPILER_ERROR", "message": "Failed to parse JSON from PlanCompiler output."}],
                    "warnings": []
                }
                return

            compiler_report = contract.get("compiler_report", {})
            status = compiler_report.get("status", "SUCCESS")

            if status == "FAILED":
                yield {
                    "ok": False,
                    "plan_contract": contract,
                    "errors": compiler_report.get("errors", []),
                    "warnings": compiler_report.get("warnings", [])
                }
                return

            yield {
                "ok": True,
                "plan_contract": contract,
                "errors": compiler_report.get("errors", []),
                "warnings": compiler_report.get("warnings", [])
            }

        except Exception as e:
            logger.exception(f"PlanCompiler model call failed: {e}")
            yield {
                "ok": False,
                "plan_contract": None,
                "errors": [{"type": "COMPILER_EXCEPTION", "message": str(e)}],
                "warnings": []
            }
