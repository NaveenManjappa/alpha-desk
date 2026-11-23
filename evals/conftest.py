"""Fixtures for the evals, and the summary printed at the end of `make eval`.

The evals run the real agent: the configured model, Finnhub and SEC EDGAR, from `.env`.
Only the checkpointer differs: always in memory, so eval threads never reach Postgres.
"""

import os

# DeepEval reads these when it is imported, so they are set before anything imports it.
# No anonymous usage data is sent, and our `.env` is read by our settings, not by DeepEval.
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "1")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")

from collections.abc import AsyncIterator, Iterator  # noqa: E402

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from langchain_core.tracers.langchain import wait_for_all_tracers  # noqa: E402
from langgraph.graph.state import CompiledStateGraph  # noqa: E402

from alphadesk.agents.research_agent import load_system_prompt  # noqa: E402
from alphadesk.api.dependencies import open_research_agent  # noqa: E402
from alphadesk.config.settings import Settings, get_settings  # noqa: E402
from alphadesk.graph.checkpointer import create_checkpointer  # noqa: E402
from alphadesk.integrations.llm import get_chat_model, get_model_name, get_model_price  # noqa: E402
from alphadesk.integrations.tracing import configure_tracing  # noqa: E402
from evals.judge import FactoryJudge  # noqa: E402
from evals.markdown import report_markdown  # noqa: E402
from evals.report import EvalSession, build_report, save_report, summary_lines  # noqa: E402

_SESSION_KEY = pytest.StashKey[EvalSession]()


@pytest.fixture(scope="session")
def eval_settings() -> Iterator[Settings]:
    """The real settings, with tracing set up as the app does it."""
    settings = get_settings()
    configure_tracing(settings)
    yield settings
    # Traces are sent from a background thread; wait so the last runs are not dropped.
    wait_for_all_tracers()


@pytest.fixture(scope="session")
def eval_session(request: pytest.FixtureRequest, eval_settings: Settings) -> EvalSession:
    """The run's shared record. Kept on the pytest config so the summary hook can read it."""
    judge = FactoryJudge(
        get_chat_model("large", eval_settings),
        model_name=get_model_name("large", eval_settings),
        price=get_model_price("large", eval_settings),
    )
    session = EvalSession(settings=eval_settings, judge=judge)
    request.config.stash[_SESSION_KEY] = session
    return session


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def research_agent(eval_settings: Settings) -> AsyncIterator[CompiledStateGraph]:
    """The real research agent, shared by every case. Each case uses its own thread."""
    async with open_research_agent(eval_settings, create_checkpointer()) as agent:
        yield agent


def pytest_terminal_summary(
    terminalreporter: pytest.TerminalReporter, config: pytest.Config
) -> None:
    """After the evals: one line per case, the overall score, and the saved results file.

    Does nothing in a run with no evals, such as `make check`.
    """
    session = config.stash.get(_SESSION_KEY, None)
    if session is None or not session.results:
        return
    settings = session.settings
    report = build_report(
        session.results,
        agent_model=get_model_name("small", settings),
        judge_model=session.judge.get_model_name(),
        system_prompt=load_system_prompt(),
        judge_tokens=(session.judge.input_tokens, session.judge.output_tokens),
        judge_price=get_model_price("large", settings),
    )
    paths = save_report(report, report_markdown(report))
    terminalreporter.section("AlphaDesk eval results")
    for line in summary_lines(report):
        terminalreporter.write_line(line)
    for path in paths:
        terminalreporter.write_line(f"Saved to {path}")
