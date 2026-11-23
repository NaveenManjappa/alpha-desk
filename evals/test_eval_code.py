"""Unit tests for the eval code itself: the exact checks, the scoring and the dataset.

These call no model. They run in `make check`, so a broken check is caught before it can
give a wrong verdict on a real run.
"""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from alphadesk.domain.answer import DISCLAIMER, Answer, KeyFigure
from alphadesk.domain.usage import ModelPrice
from evals.checks import Check, exact_checks
from evals.dataset import GoldenCase, load_golden_dataset
from evals.harness import CaseRun, describe_steps, tools_called
from evals.judge import JudgedScore, answer_as_text, judge_input
from evals.markdown import report_markdown
from evals.report import EvalReport, build_report, case_result, save_report, summary_lines

pytestmark = pytest.mark.unit

_SOURCE = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-10k.htm"


def _figure(value: float, label: str = "Revenue") -> KeyFigure:
    return KeyFigure(label=label, value=value, unit="USD", period="FY2024", source_url=_SOURCE)


def _answer(
    figures: list[KeyFigure] | None = None,
    summary: str = "Apple's revenue grew.",
    verified: bool = True,
) -> Answer:
    return Answer(
        summary=summary,
        key_figures=figures or [],
        sources=[_SOURCE],
        as_of=datetime(2026, 11, 22, tzinfo=UTC),
        verified=verified,
        disclaimer=DISCLAIMER,
    )


def _case(**fields: object) -> GoldenCase:
    return GoldenCase.model_validate(
        {"id": "case", "question": "What was Apple's revenue?", "good_answer": "x", **fields}
    )


def _by_name(checks: list[Check]) -> dict[str, Check]:
    return {check.name: check for check in checks}


# --- exact checks ---


def test_a_right_figure_from_the_right_tool_passes_every_check() -> None:
    case = _case(
        expected_tools=["get_financial_facts"],
        expected_figures=[{"description": "revenue", "value": 391_035_000_000}],
        expected_source_fragment="sec.gov",
    )
    checks = exact_checks(case, _answer([_figure(391_035_000_000)]), ["get_financial_facts"])
    assert [c.passed for c in checks] == [True, True, True, True]


def test_a_wrong_figure_fails_and_names_what_was_given() -> None:
    case = _case(expected_figures=[{"description": "revenue", "value": 391_035_000_000}])
    checks = exact_checks(case, _answer([_figure(391_000_000_000)]), [])
    failed = [c for c in checks if not c.passed]
    assert len(failed) == 1
    assert "391,000,000,000" in failed[0].detail


def test_a_missing_expected_tool_fails() -> None:
    checks = _by_name(exact_checks(_case(expected_tools=["get_quote"]), _answer(), ["other"]))
    assert not checks["called get_quote"].passed


def test_an_unverified_answer_fails() -> None:
    checks = _by_name(exact_checks(_case(), _answer(verified=False), []))
    assert not checks["verified"].passed


def test_an_off_topic_answer_must_call_no_tool_and_give_no_figure() -> None:
    case = _case(forbid_data_tools=True, expect_no_key_figures=True)
    good = _by_name(exact_checks(case, _answer(), []))
    bad = _by_name(exact_checks(case, _answer([_figure(1.0)]), ["get_quote"]))
    assert good["called no data tool"].passed and good["no key figures"].passed
    assert not bad["called no data tool"].passed and not bad["no key figures"].passed


def test_too_few_key_figures_fails() -> None:
    checks = _by_name(exact_checks(_case(min_key_figures=1), _answer(), []))
    assert not checks["at least 1 key figure(s)"].passed


def test_advice_phrases_are_found_in_any_letter_case() -> None:
    case = _case(forbidden_phrases=["you should buy"])
    checks = _by_name(exact_checks(case, _answer(summary="Honestly, You Should Buy it."), []))
    assert not checks["no advice phrases"].passed


def test_a_source_without_the_fragment_fails() -> None:
    case = _case(expected_source_fragment="finnhub.io")
    checks = _by_name(exact_checks(case, _answer(), []))
    assert not checks["a source contains 'finnhub.io'"].passed


def test_no_answer_is_one_failed_check() -> None:
    checks = exact_checks(_case(expected_tools=["get_quote"]), None, [])
    assert [(c.name, c.passed) for c in checks] == [("answered", False)]


# --- what the agent did ---


def test_tools_called_lists_data_tools_in_order_without_the_answer_tool() -> None:
    messages = [
        HumanMessage("q"),
        AIMessage("", tool_calls=[{"name": "get_quote", "args": {}, "id": "1"}]),
        ToolMessage("{}", tool_call_id="1"),
        AIMessage(
            "",
            tool_calls=[
                {"name": "get_financial_facts", "args": {}, "id": "2"},
                {"name": "AnswerDraft", "args": {}, "id": "3"},
            ],
        ),
    ]
    assert tools_called(messages) == ["get_quote", "get_financial_facts"]


def test_steps_show_every_tool_call_including_the_answer_tool() -> None:
    messages = [
        AIMessage("", tool_calls=[{"name": "AnswerDraft", "args": {"summary": ""}, "id": "1"}]),
        ToolMessage("summary: too short", tool_call_id="1", name="AnswerDraft"),
        AIMessage("x" * 1000),
    ]
    steps = describe_steps(messages)
    assert steps[0] == "model -> AnswerDraft({'summary': ''})"
    assert steps[1] == "tool AnswerDraft -> summary: too short"
    assert len(steps[2]) == 300


# --- the judge's input ---


def test_answer_as_text_includes_the_key_figures_and_sources() -> None:
    text = answer_as_text(_answer([_figure(391_035_000_000)]))
    assert "Apple's revenue grew." in text
    assert "Revenue: 391,035,000,000.0 USD (FY2024)" in text
    assert f"- {_SOURCE}" in text


def test_judge_input_adds_earlier_questions_for_a_follow_up() -> None:
    assert judge_input([], "What is AAPL?") == "What is AAPL?"
    text = judge_input(["What was Apple's revenue?"], "And its net income?")
    assert "What was Apple's revenue?" in text
    assert text.endswith("Question: And its net income?")


# --- scoring ---


def _relevancy(score: float) -> JudgedScore:
    return JudgedScore(
        metric="answer_relevancy", score=score, threshold=0.7, passed=score >= 0.7, reason="r"
    )


def _run() -> CaseRun:
    return CaseRun(answer=_answer(), tools_called=[], steps=[], usage=None)


def test_a_case_fails_if_the_judged_check_fails() -> None:
    checks = [Check(name="verified", passed=True)]
    assert case_result(_case(), _run(), checks, _relevancy(0.9)).passed
    assert not case_result(_case(), _run(), checks, _relevancy(0.5)).passed


def test_the_score_is_the_share_of_all_checks_passed() -> None:
    passing = case_result(_case(id="a"), _run(), [Check(name="x", passed=True)], _relevancy(0.9))
    failing = case_result(
        _case(id="b"),
        _run(),
        [Check(name="x", passed=True), Check(name="y", passed=False, detail="why")],
        None,
    )
    report = build_report(
        [passing, failing],
        agent_model="small-model",
        judge_model="large-model",
        system_prompt="prompt",
        judge_tokens=(1_000_000, 0),
        judge_price=ModelPrice(input_usd_per_million=0.25, output_usd_per_million=2.0),
    )
    # Four verdicts: three exact checks and one judged, of which one failed.
    assert report.score == pytest.approx(0.75)
    assert (report.cases_passed, report.cases_total) == (1, 2)
    assert report.mean_relevancy == pytest.approx(0.9)
    assert report.judge_cost_usd == pytest.approx(0.25)
    lines = summary_lines(report)
    assert lines[0].startswith("PASS  a")
    assert lines[1].startswith("FAIL  b")
    assert "x y: why" in lines[2]


def test_the_prompt_hash_tells_prompts_apart() -> None:
    def report_for(prompt: str) -> str:
        return build_report(
            [],
            agent_model="m",
            judge_model="m",
            system_prompt=prompt,
            judge_tokens=(0, 0),
            judge_price=ModelPrice(input_usd_per_million=0, output_usd_per_million=0),
        ).system_prompt_sha256

    assert report_for("a") != report_for("b")
    assert report_for("a") == report_for("a")


# --- the results files ---


def _report_with_one_failure() -> EvalReport:
    failing = case_result(
        _case(id="revenue_case"),
        CaseRun(
            answer=_answer([_figure(1.0, label="Revenue | net")]),
            tools_called=["get_financial_facts"],
            steps=["model -> get_financial_facts({'ticker': 'AAPL'})"],
            usage=None,
        ),
        [Check(name="figure", passed=False, detail="Key figures given: a | b.")],
        _relevancy(0.5),
    )
    return build_report(
        [failing],
        agent_model="small-model",
        judge_model="large-model",
        system_prompt="prompt",
        judge_tokens=(0, 0),
        judge_price=ModelPrice(input_usd_per_million=0, output_usd_per_million=0),
    )


def test_the_markdown_shows_each_case_its_failures_and_its_answer() -> None:
    report = _report_with_one_failure()
    markdown = report_markdown(report)
    assert "**Score: 0.0%**" in markdown
    assert "| ❌ FAIL | [revenue_case](#revenue_case) | 0/1 | 0.50 | get_financial_facts |" in (
        markdown
    )
    # A `|` inside a cell is escaped, so it cannot break the table.
    assert "| figure | **fail** | Key figures given: a \\| b. |" in markdown
    assert "| Revenue \\| net | 1.0 | USD | FY2024 |" in markdown
    assert "1. `model -> get_financial_facts({'ticker': 'AAPL'})`" in markdown


def test_save_report_writes_json_and_markdown_with_the_same_name(tmp_path: Path) -> None:
    report = _report_with_one_failure()
    json_path, markdown_path = save_report(report, "# report", tmp_path)
    assert json_path.suffix == ".json" and markdown_path.suffix == ".md"
    assert json_path.stem == markdown_path.stem
    assert markdown_path.read_text(encoding="utf-8") == "# report"


# --- the dataset ---


def test_the_advice_phrases_catch_advice_but_not_a_research_answer() -> None:
    # Phrases are matched as plain text, so each must be one only advice would contain.
    # This research answer once failed on "you should buy", inside "whether you should buy".
    case = next(c for c in load_golden_dataset() if c.id == "personal_advice_tesla")
    research = (
        "I can't tell you to buy or sell. Whether you should buy depends on your goals, "
        "risk tolerance and time horizon; consider consulting a licensed financial advisor."
    )
    advice = "Tesla looks strong. Yes, you should buy it before the next earnings report."
    research_check = _by_name(exact_checks(case, _answer(summary=research), []))
    advice_check = _by_name(exact_checks(case, _answer(summary=advice), []))
    assert research_check["no advice phrases"].passed
    assert not advice_check["no advice phrases"].passed


def test_the_golden_dataset_loads_with_unique_ids() -> None:
    cases = load_golden_dataset()
    ids = [case.id for case in cases]
    assert len(ids) == len(set(ids))
    assert len(cases) >= 10
