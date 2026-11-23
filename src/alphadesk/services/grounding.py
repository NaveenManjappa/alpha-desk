"""The grounding check: every number in an answer must come from this run's tool results.

Plain Python, no model call. A second LLM asked "is this grounded?" could be wrong in the
same way the first one was; comparing numbers and URLs in code cannot be talked round.

Rounding tolerance. Tool values reach the model as JSON and the model copies them back,
so in the normal case they match exactly. The tolerance only forgives harmless rounding:

- `ABSOLUTE_TOLERANCE` (half a cent) lets a price or per-share figure be rounded to cents,
  e.g. EPS 13.6427 written as 13.64. Prices and EPS are quoted in cents, so a smaller
  difference never changes what the reader sees.
- `RELATIVE_TOLERANCE` (0.01%, one part in 10,000) lets a large figure lose its last
  digits, e.g. revenue 245,122,000,000 written as 245,120,000,000.

Anything looser starts to let through numbers that differ in a way a reader would notice:
at 0.05% "245 billion" would pass for 245.122 billion. A number passes if it is within
either tolerance (`math.isclose` semantics).
"""

import logging
import math
from collections.abc import Sequence
from typing import assert_never

from pydantic import BaseModel

from alphadesk.domain.answer import Answer, AnswerDraft, KeyFigure
from alphadesk.domain.tool_results import (
    FinancialFactsResult,
    QuoteResult,
    RecentFilingsResult,
    ToolError,
    ToolResult,
)

logger = logging.getLogger(__name__)

ABSOLUTE_TOLERANCE = 0.005
RELATIVE_TOLERANCE = 1e-4


class GroundingFailure(BaseModel):
    """A key figure that could not be matched to the tool results.

    Attributes:
        figure: The figure as the model wrote it.
        reasons: One plain sentence per failed check, written so the model can act on it.
    """

    figure: KeyFigure
    reasons: list[str]


def check_grounding(
    answer: AnswerDraft, tool_results: Sequence[ToolResult]
) -> list[GroundingFailure]:
    """Check every key figure against this run's tool results.

    A figure passes when its value matches a number some tool returned (within the
    rounding tolerance) and its `source_url` is a URL some tool returned. The two checks
    are independent: the number and the URL need not come from the same result.

    Args:
        answer: The answer to check. An `Answer` works too, since it extends `AnswerDraft`.
        tool_results: Every data tool result from this run. Failed calls (`ToolError`)
            contribute nothing: no data came back from them.

    Returns:
        One failure per figure that did not pass, in answer order. Empty means grounded.
    """
    numbers, urls = _evidence(tool_results)
    failures: list[GroundingFailure] = []
    for figure in answer.key_figures:
        reasons: list[str] = []
        if not any(_same_number(figure.value, number) for number in numbers):
            reasons.append(f"The value {figure.value} does not match any number a tool returned.")
        if figure.source_url not in urls:
            reasons.append(f"The source_url {figure.source_url} was not returned by any tool.")
        if reasons:
            failures.append(GroundingFailure(figure=figure, reasons=reasons))
    if failures:
        logger.warning(
            "Grounding check failed for %d of %d figures: %s",
            len(failures),
            len(answer.key_figures),
            [failure.figure.label for failure in failures],
        )
    return failures


def apply_grounding(answer: Answer, failures: Sequence[GroundingFailure]) -> Answer:
    """Set `verified` from the check, removing any figure that failed.

    Args:
        answer: The finished answer.
        failures: What `check_grounding` returned for it.

    Returns:
        A copy with `verified=True` if nothing failed; otherwise with the failed figures
        removed and `verified=False`, so the reader knows something was taken out.
    """
    failed = [failure.figure for failure in failures]
    kept = [figure for figure in answer.key_figures if figure not in failed]
    return answer.model_copy(update={"key_figures": kept, "verified": not failures})


def _evidence(tool_results: Sequence[ToolResult]) -> tuple[list[float], set[str]]:
    """Every number and every URL the tools returned.

    Listed field by field, so it is obvious what counts as evidence. `assert_never` makes
    pyright flag this function when a new tool result type is added.
    """
    numbers: list[float] = []
    urls: set[str] = set()
    for result in tool_results:
        match result:
            case QuoteResult():
                numbers += [result.price, result.change]
                urls.add(result.source_url)
            case FinancialFactsResult():
                numbers += [fact.value for fact in result.facts]
                urls.add(result.source_url)
                urls.update(fact.source_url for fact in result.facts)
            case RecentFilingsResult():
                urls.add(result.source_url)
                urls.update(filing.url for filing in result.filings)
            case ToolError():
                pass
            case _:
                assert_never(result)
    return numbers, urls


def _same_number(claimed: float, returned: float) -> bool:
    """True if two numbers differ by no more than rounding (see module docstring)."""
    return math.isclose(claimed, returned, rel_tol=RELATIVE_TOLERANCE, abs_tol=ABSOLUTE_TOLERANCE)
