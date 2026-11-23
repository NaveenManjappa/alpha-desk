"""Exact checks: questions with one right answer, checked in plain code.

No model is involved, so a check gives the same verdict on the same answer every time.
That is why everything that *can* be checked exactly is checked here, and only answer
relevance is left to an LLM judge (`judge.py`). In finance a judge saying "looks right" is
not good enough for a number: the revenue either matches the 10-K or it does not.
"""

import math
from collections.abc import Sequence

from pydantic import BaseModel

from alphadesk.domain.answer import Answer
from evals.dataset import GoldenCase

# How close a figure must be to the expected value. Figures are copied, not calculated,
# so they should match exactly; this only absorbs float noise from the JSON round trip.
_RELATIVE_TOLERANCE = 1e-9


class Check(BaseModel):
    """The verdict of one check on one answer.

    Attributes:
        name: What was checked, e.g. "called get_quote".
        passed: Whether the answer passed.
        detail: Why it failed, or empty when it passed.
    """

    name: str
    passed: bool
    detail: str = ""


def exact_checks(
    case: GoldenCase, answer: Answer | None, tools_called: Sequence[str]
) -> list[Check]:
    """Run every exact check the case asks for.

    Args:
        case: The golden case, whose fields choose the checks.
        answer: The agent's answer, or None if the run ended without one.
        tools_called: The data tools called in the checked turn, in order.

    Returns:
        One `Check` per rule. With no answer, a single failed "answered" check, since no
        other check can be run.
    """
    if answer is None:
        return [Check(name="answered", passed=False, detail="The run ended without an answer.")]

    checks = [check_verified(answer)]
    checks += [check_tool_called(tools_called, tool) for tool in case.expected_tools]
    if case.forbid_repeated_tools:
        checks.append(check_no_repeated_tools(tools_called))
    if case.forbid_data_tools:
        checks.append(check_no_data_tools(tools_called))
    checks += [
        check_figure(answer, figure.description, figure.value) for figure in case.expected_figures
    ]
    if case.min_key_figures:
        checks.append(check_min_key_figures(answer, case.min_key_figures))
    if case.expect_no_key_figures:
        checks.append(check_no_key_figures(answer))
    if case.expected_source_fragment:
        checks.append(check_source_contains(answer, case.expected_source_fragment))
    if case.forbidden_phrases:
        checks.append(check_no_forbidden_phrases(answer, case.forbidden_phrases))
    return checks


def check_verified(answer: Answer) -> Check:
    """Every key figure passed the grounding check."""
    if answer.verified:
        return Check(name="verified", passed=True)
    return Check(
        name="verified",
        passed=False,
        detail="verified is False: a figure did not match any tool result and was removed.",
    )


def check_tool_called(tools_called: Sequence[str], tool: str) -> Check:
    """The expected data tool was called in this turn."""
    name = f"called {tool}"
    if tool in tools_called:
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"Tools called: {_list_or_none(tools_called)}.")


def check_no_repeated_tools(tools_called: Sequence[str]) -> Check:
    """No data tool was asked for twice. A refused repeat counts: the model still asked."""
    name = "no repeated tool call"
    if len(set(tools_called)) == len(tools_called):
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"Tools called: {_list_or_none(tools_called)}.")


def check_no_data_tools(tools_called: Sequence[str]) -> Check:
    """No data tool was called: the question needed no live data."""
    name = "called no data tool"
    if not tools_called:
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"Tools called: {_list_or_none(tools_called)}.")


def check_figure(answer: Answer, description: str, expected: float) -> Check:
    """Some key figure equals the expected value."""
    name = f"figure: {description} = {expected:,}"
    for figure in answer.key_figures:
        if math.isclose(figure.value, expected, rel_tol=_RELATIVE_TOLERANCE):
            return Check(name=name, passed=True)
    found = ", ".join(f"{f.label} = {f.value:,}" for f in answer.key_figures) or "none"
    return Check(name=name, passed=False, detail=f"Key figures given: {found}.")


def check_min_key_figures(answer: Answer, minimum: int) -> Check:
    """The answer has at least `minimum` key figures."""
    name = f"at least {minimum} key figure(s)"
    count = len(answer.key_figures)
    if count >= minimum:
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"The answer has {count}.")


def check_no_key_figures(answer: Answer) -> Check:
    """The answer gives no number."""
    name = "no key figures"
    if not answer.key_figures:
        return Check(name=name, passed=True)
    labels = ", ".join(f.label for f in answer.key_figures)
    return Check(name=name, passed=False, detail=f"Key figures given: {labels}.")


def check_source_contains(answer: Answer, fragment: str) -> Check:
    """Some source URL contains `fragment`, e.g. "sec.gov"."""
    name = f"a source contains {fragment!r}"
    if any(fragment in source for source in answer.sources):
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"Sources: {_list_or_none(answer.sources)}.")


def check_no_forbidden_phrases(answer: Answer, phrases: Sequence[str]) -> Check:
    """The summary contains none of `phrases`, ignoring letter case."""
    name = "no advice phrases"
    summary = answer.summary.casefold()
    found = [phrase for phrase in phrases if phrase.casefold() in summary]
    if not found:
        return Check(name=name, passed=True)
    return Check(name=name, passed=False, detail=f"Summary contains: {', '.join(found)}.")


def _list_or_none(items: Sequence[str]) -> str:
    return ", ".join(items) or "none"
