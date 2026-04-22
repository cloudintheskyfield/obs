from src.omni_agent.agents.streaming_agent import StreamingAgent


def test_strip_obs_tags_removes_internal_markup() -> None:
    raw = "<obs:todo>one|two</obs:todo>\nVisible answer\n<obs:done>1</obs:done>"
    assert StreamingAgent._strip_obs_tags(raw).strip() == "Visible answer"
