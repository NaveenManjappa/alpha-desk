"""Tests for the grounding check: every key figure must match this run's tool results."""

import ast
import inspect
from datetime import UTC, date, datetime

import pytest

import alphadesk.services.grounding as grounding_module
from alphadesk.domain.answer import DISCLAIMER, Answer, AnswerDraft, KeyFigure
from alphadesk.domain.filings import Filing
from alphadesk.domain.tool_results import (
    FinancialFact,
    FinancialFactsResult,
    QuoteResult,
    RecentFilingsResult,
    ToolError,
    ToolResult,
)
from alphadesk.services.grounding import apply_grounding, check_grounding

FETCHED_AT = datetime(2026, 11, 13, 9, 0, tzinfo=UTC)
QUOTE_URL = "https://finnhub.io/api/v1/quote?symbol=AAPL"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
TEN_K_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/"
FILINGS_URL = "https://data.sec.gov/submissions/CIK0000789019.json"
FILING_URL = "https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/msft-10k.htm"

QUOTE = QuoteResult(
    ticker="AAPL",
    price=227.5,
    change=1.25,
    quote_time=datetime(2026, 11, 12, 21, 0, tzinfo=UTC),
    source_url=QUOTE_URL,
    as_of=FETCHED_AT,
)
FACTS = FinancialFactsResult(
    ticker="MSFT",
    facts=[
        FinancialFact(
            metric="revenue",
            value=245_122_000_000,
            unit="USD",
            period_start=date(2024, 7, 1),
            period_end=date(2025, 6, 30),
            source_url=TEN_K_URL,
        ),
        FinancialFact(
            metric="eps_diluted",
            value=13.6427,
            unit="USD per share",
            period_start=date(2024, 7, 1),
            period_end=date(2025, 6, 30),
            source_url=TEN_K_URL,
        ),
    ],
    source_url=FACTS_URL,
    as_of=FETCHED_AT,
)
FILINGS = RecentFilingsResult(
    ticker="MSFT",
    filings=[
        Filing(
            form="10-K",
            filing_date=date(2025, 7, 30),
            report_date=date(2025, 6, 30),
            url=FILING_URL,
        )
    ],
    source_url=FILINGS_URL,
    as_of=FETCHED_AT,
)
QUOTE_FAILED = ToolError(
    error_type="upstream_error",
    message="The quote provider did not answer.",
    source_url="https://finnhub.io/api/v1/quote?symbol=TSLA",
    as_of=FETCHED_AT,
)
ALL_RESULTS: list[ToolResult] = [QUOTE, FACTS, FILINGS, QUOTE_FAILED]


def _figure(value: float, source_url: str = QUOTE_URL, label: str = "Share price") -> KeyFigure:
    return KeyFigure(label=label, value=value, unit="USD", period="FY2025", source_url=source_url)


def _draft(*figures: KeyFigure) -> AnswerDraft:
    return AnswerDraft(
        summary="A summary.",
        key_figures=list(figures),
        sources=sorted({figure.source_url for figure in figures}),
    )


def _answer(*figures: KeyFigure) -> Answer:
    return Answer(
        **_draft(*figures).model_dump(),
        as_of=FETCHED_AT,
        verified=False,
        disclaimer=DISCLAIMER,
    )


# --- check_grounding: what passes -------------------------------------------------------


@pytest.mark.unit
def test_figure_copied_from_a_quote_passes() -> None:
    answer = _draft(_figure(227.5), _figure(1.25, label="Change"))

    assert check_grounding(answer, ALL_RESULTS) == []


@pytest.mark.unit
@pytest.mark.parametrize("source_url", [TEN_K_URL, FACTS_URL])
def test_financial_fact_may_cite_the_10k_or_the_edgar_data(source_url: str) -> None:
    answer = _draft(_figure(245_122_000_000, source_url=source_url, label="Revenue"))

    assert check_grounding(answer, ALL_RESULTS) == []


@pytest.mark.unit
def test_filing_link_is_a_source_a_tool_returned() -> None:
    # A real number (the price) cited to a filing link: both checks pass on their own.
    answer = _draft(_figure(227.5, source_url=FILING_URL))

    assert check_grounding(answer, ALL_RESULTS) == []


@pytest.mark.unit
def test_answer_without_figures_passes() -> None:
    assert check_grounding(_draft(), []) == []


# --- check_grounding: what is caught ----------------------------------------------------


@pytest.mark.unit
def test_invented_number_is_caught() -> None:
    invented = _figure(231.0)

    failures = check_grounding(_draft(_figure(227.5), invented), ALL_RESULTS)

    assert [failure.figure for failure in failures] == [invented]
    assert len(failures[0].reasons) == 1
    assert "231" in failures[0].reasons[0]


@pytest.mark.unit
def test_real_number_with_a_made_up_url_is_caught() -> None:
    made_up = _figure(227.5, source_url="https://example.com/apple-price")

    failures = check_grounding(_draft(made_up), ALL_RESULTS)

    assert [failure.figure for failure in failures] == [made_up]
    assert len(failures[0].reasons) == 1
    assert "https://example.com/apple-price" in failures[0].reasons[0]


@pytest.mark.unit
def test_figure_wrong_on_both_counts_reports_both_reasons() -> None:
    failures = check_grounding(_draft(_figure(1.0, source_url="https://x.test/")), ALL_RESULTS)

    assert len(failures) == 1
    assert len(failures[0].reasons) == 2


@pytest.mark.unit
def test_url_from_a_failed_tool_call_is_not_a_source() -> None:
    # The tool tried this address and got no data, so nothing can be sourced from it.
    figure = _figure(227.5, source_url=QUOTE_FAILED.source_url or "")

    assert len(check_grounding(_draft(figure), ALL_RESULTS)) == 1


@pytest.mark.unit
def test_nothing_passes_when_no_tool_ran() -> None:
    assert len(check_grounding(_draft(_figure(227.5)), [])) == 1


@pytest.mark.unit
def test_sign_flip_is_caught() -> None:
    # A loss reported as a positive number is a different number.
    assert len(check_grounding(_draft(_figure(-227.5)), [QUOTE])) == 1


# --- check_grounding: rounding tolerance -------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool_value", "model_value"),
    [
        (13.6427, 13.64),  # per-share figure rounded to cents
        (227.5, 227.50),  # same number written differently
        (245_122_000_000, 245_120_000_000),  # large figure rounded, 0.001% off
        (0.1 + 0.2, 0.3),  # float noise
    ],
)
def test_rounding_within_tolerance_passes(tool_value: float, model_value: float) -> None:
    result = QUOTE.model_copy(update={"price": tool_value})

    assert check_grounding(_draft(_figure(model_value)), [result]) == []


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool_value", "model_value"),
    [
        (13.6427, 13.65),  # a cent past rounding
        (227.5, 227.6),  # a different price
        (245_122_000_000, 245_000_000_000),  # rounded to 3 significant figures: 0.05% off
        (245_122_000_000, 247_000_000_000),  # invented revenue, under 1% off
    ],
)
def test_difference_beyond_tolerance_is_caught(tool_value: float, model_value: float) -> None:
    result = QUOTE.model_copy(update={"price": tool_value})

    assert len(check_grounding(_draft(_figure(model_value)), [result])) == 1


# --- apply_grounding --------------------------------------------------------------------


@pytest.mark.unit
def test_apply_with_no_failures_marks_the_answer_verified() -> None:
    answer = _answer(_figure(227.5))

    grounded = apply_grounding(answer, [])

    assert grounded.verified is True
    assert grounded.key_figures == answer.key_figures


@pytest.mark.unit
def test_apply_with_failures_removes_bad_figures_and_marks_unverified() -> None:
    good, bad = _figure(227.5), _figure(231.0)
    answer = _answer(good, bad)

    grounded = apply_grounding(answer, check_grounding(answer, ALL_RESULTS))

    assert grounded.verified is False
    assert grounded.key_figures == [good]
    assert (grounded.summary, grounded.disclaimer) == (answer.summary, answer.disclaimer)


# --- No LLM inside the check -------------------------------------------------------------


@pytest.mark.unit
def test_grounding_module_imports_no_llm_library() -> None:
    tree = ast.parse(inspect.getsource(grounding_module))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    forbidden = ("langchain", "langgraph", "openai", "alphadesk.integrations")
    assert not [name for name in imported if name.startswith(forbidden)]
