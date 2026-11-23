"""The golden-dataset evals: each case asks the real agent and checks its answer.

Run with `make eval`. Each case is one pytest test, so a failed check fails the run.

DeepEval's own `assert_test` is not used: it runs its metrics on an event loop of its own,
which cannot start inside these async tests. The metric is awaited directly instead and
its verdict asserted, which is what `assert_test` does underneath.
"""

import pytest
from langgraph.graph.state import CompiledStateGraph

from alphadesk.integrations.llm import get_model_price
from evals.checks import exact_checks
from evals.dataset import GoldenCase, load_golden_dataset
from evals.harness import run_case
from evals.judge import judge_input, judge_relevancy
from evals.report import EvalSession, case_result

# Every test here calls a real LLM, so all are marked `eval`. They share the session's
# event loop, as the agent fixture (and its HTTP clients) are created on it.
pytestmark = [pytest.mark.eval, pytest.mark.asyncio(loop_scope="session")]

CASES = load_golden_dataset()


@pytest.mark.parametrize("case", CASES, ids=[case.id for case in CASES])
async def test_golden_case(
    case: GoldenCase, research_agent: CompiledStateGraph, eval_session: EvalSession
) -> None:
    run = await run_case(research_agent, case, get_model_price("small", eval_session.settings))

    checks = exact_checks(case, run.answer, run.tools_called)
    relevancy = None
    if case.judge_relevancy and run.answer is not None:
        relevancy = await judge_relevancy(
            eval_session.judge, judge_input(case.setup, case.question), run.answer
        )

    result = case_result(case, run, checks, relevancy)
    eval_session.results.append(result)

    failed = [f"{check.name}: {check.detail}" for check in checks if not check.passed]
    if relevancy is not None and not relevancy.passed:
        failed.append(f"relevancy {relevancy.score:.2f} < {relevancy.threshold}")
    assert result.passed, "; ".join(failed)
