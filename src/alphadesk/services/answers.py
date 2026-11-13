"""Turn the model's `AnswerDraft` into the full `Answer` contract.

Plain code, no LangChain: the fields set here (`as_of`, `verified`, `disclaimer`) must be
right every time, so they are never left to the model.
"""

from collections.abc import Sequence
from datetime import datetime

from alphadesk.domain.answer import DISCLAIMER, Answer, AnswerDraft


def finalise_answer(
    draft: AnswerDraft, data_fetched_at: Sequence[datetime], answered_at: datetime
) -> Answer:
    """Add the code-owned fields to a draft answer.

    Args:
        draft: What the model returned.
        data_fetched_at: The `as_of` time of every tool result in this run.
        answered_at: When the agent finished (UTC). Used as `as_of` when no tool ran,
            for example for a question that needs no live data.

    Returns:
        The complete `Answer`, with the fixed disclaimer and `verified` set to False
        (the grounding check arrives in Slice 7).
    """
    as_of = min(data_fetched_at) if data_fetched_at else answered_at
    return Answer.model_validate(
        {
            **draft.model_dump(),
            "as_of": as_of,
            "verified": False,
            "disclaimer": DISCLAIMER,
        }
    )
