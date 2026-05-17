"""Five-agent Harness runtime roles."""

__all__ = [
    "PlannerAgent",
    "SearchAgent",
    "GeneratorAgent",
    "RunnerAgent",
    "EvaluatorAgent",
    "HarnessRuntime",
    "HarnessEngine",
]


def __getattr__(name: str):
    if name == "PlannerAgent":
        from .planner_agent import PlannerAgent

        return PlannerAgent
    if name == "SearchAgent":
        from .search_agent import SearchAgent

        return SearchAgent
    if name == "GeneratorAgent":
        from .generator_agent import GeneratorAgent

        return GeneratorAgent
    if name == "RunnerAgent":
        from .runner_agent import RunnerAgent

        return RunnerAgent
    if name == "EvaluatorAgent":
        from .evaluator_agent import EvaluatorAgent

        return EvaluatorAgent
    if name == "HarnessRuntime":
        from .harness_runtime import HarnessRuntime

        return HarnessRuntime
    if name == "HarnessEngine":
        from .harness_engine import HarnessEngine

        return HarnessEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
