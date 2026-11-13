"""The answer contract: the typed object the research agent returns (phase 1 spec).

It is split in two on purpose:

- `AnswerDraft` is what the model fills in. Its schema is sent to the model, so the
  docstrings and field descriptions below are written for the model to read.
- `Answer` adds the fields only code may set: `as_of`, `verified` and `disclaimer`. The
  model never sees them, so it cannot get them wrong or leave them out.
"""

from pydantic import AwareDatetime, BaseModel, Field

DISCLAIMER = "AlphaDesk provides research, not financial advice."


class KeyFigure(BaseModel):
    """One number in the answer, copied from a tool result, with where it came from."""

    label: str = Field(min_length=1, description='What the number is, e.g. "Revenue".')
    value: float = Field(
        allow_inf_nan=False,
        description="The number exactly as the tool returned it. Do not round or convert it.",
    )
    unit: str = Field(
        min_length=1, description='The unit as the tool returned it, e.g. "USD" or "USD per share".'
    )
    period: str = Field(
        min_length=1,
        description='The fiscal year, date range or time the number is for, e.g. "FY2025".',
    )
    source_url: str = Field(
        pattern=r"^https?://\S+$",
        description="The source_url the tool returned with this number.",
    )


class AnswerDraft(BaseModel):
    """Your final answer to the user. Call this once you have the data you need.

    Every number goes in key_figures, never in the summary.
    """

    summary: str = Field(
        min_length=1,
        description=(
            "Two to five plain sentences answering the question. No numbers here: "
            "refer to key figures in words, e.g. 'revenue grew'."
        ),
    )
    key_figures: list[KeyFigure] = Field(
        description="Every number the answer relies on, each from a tool result. May be empty."
    )
    sources: list[str] = Field(
        description="Every source_url from the tool results you used. May be empty."
    )


class Answer(AnswerDraft):
    """The full answer contract. Built by code from an `AnswerDraft`, never by the model.

    It inherits the three model-written fields from `AnswerDraft`, so their rules are
    defined once.

    Attributes:
        as_of: When the data behind the answer was fetched (UTC). If several tools ran,
            the oldest fetch time, since an answer is only as fresh as its oldest data.
        verified: True if every figure passed the grounding check
            (`services/grounding.py`). False until that check has run, so nothing claims
            a check that never happened.
        disclaimer: Always `DISCLAIMER`.
    """

    as_of: AwareDatetime
    verified: bool
    disclaimer: str
