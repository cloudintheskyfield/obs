import pytest
import json
from agents.plan_compiler import PlanCompiler

class MockVllmClient:
    def __init__(self, response_text):
        self.response_text = response_text

    async def chat_completion(self, *args, **kwargs):
        class MockStream:
            def __init__(self, text):
                self.text = text
            async def __aiter__(self):
                # Emit in small chunks to test streaming parser logic
                for i in range(0, len(self.text), 10):
                    yield {"choices": [{"delta": {"content": self.text[i:i+10]}}]}
        return MockStream(self.response_text)

class MockHarnessEngine:
    def load_agent_prompt(self, role, default):
        return "mock prompt"

@pytest.mark.asyncio
async def test_plan_compiler_legacy_json():
    client = MockVllmClient("")
    compiler = PlanCompiler(client)
    compiler.system_prompt = "mock prompt"
    
    markdown = '{"task_id": "test_legacy", "goal": "legacy test"}'
    
    result = None
    async for item in compiler.compile(markdown, {}, {}, "mock-model", "session_id"):
        if isinstance(item, dict) and "ok" in item:
            result = item
            
    assert result["ok"] is True
    assert result["plan_contract"]["task_id"] == "test_legacy"

@pytest.mark.asyncio
async def test_plan_compiler_invalid_markdown():
    client = MockVllmClient("")
    compiler = PlanCompiler(client)
    compiler.system_prompt = "mock prompt"
    
    markdown = "Just some text without the header"
    result = None
    async for item in compiler.compile(markdown, {}, {}, "mock-model", "session_id"):
        if isinstance(item, dict) and "ok" in item:
            result = item
            
    assert result["ok"] is False
    assert result["plan_contract"] is None
    assert any(err["type"] == "PLANNER_FORMAT_ERROR" for err in result["errors"])

@pytest.mark.asyncio
async def test_plan_compiler_valid_llm_response():
    mock_response = '''
    <think>
    Thinking about the compilation...
    </think>
    ```json
    {
      "schema_version": "1.0",
      "task_id": "task_1",
      "goal": "Test goal",
      "compiler_report": {
        "status": "SUCCESS"
      }
    }
    ```
    '''
    client = MockVllmClient(mock_response)
    compiler = PlanCompiler(client)
    compiler.system_prompt = "mock prompt"
    
    markdown = "# PlannerMarkdownPlan\n\nSome plan here."
    result = None
    async for item in compiler.compile(markdown, {}, {}, "mock-model", "session_id"):
        if isinstance(item, dict) and "ok" in item:
            result = item
            
    assert result["ok"] is True
    assert result["plan_contract"]["goal"] == "Test goal"

@pytest.mark.asyncio
async def test_plan_compiler_failed_report():
    mock_response = '''
    ```json
    {
      "schema_version": "1.0",
      "task_id": "task_1",
      "goal": "Test goal",
      "compiler_report": {
        "status": "FAILED",
        "errors": [{"type": "MISSING_INFO", "message": "error"}]
      }
    }
    ```
    '''
    client = MockVllmClient(mock_response)
    compiler = PlanCompiler(client)
    compiler.system_prompt = "mock prompt"
    
    markdown = "# PlannerMarkdownPlan\n\nSome plan here."
    result = None
    async for item in compiler.compile(markdown, {}, {}, "mock-model", "session_id"):
        if isinstance(item, dict) and "ok" in item:
            result = item
            
    assert result["ok"] is False
    assert result["plan_contract"] is not None
    assert len(result["errors"]) == 1
