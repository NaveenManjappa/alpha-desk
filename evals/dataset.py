"""The golden dataset: the questions the evals ask, and what a good answer to each needs.

The cases live in `golden_dataset.json`, so a new case means adding data, not code. Each
field below switches on one check in `checks.py`. A field left at its default adds no
check.

The expected figures are real numbers from each company's 10-K. The financials tool
returns only the last three fiscal years, so when a year falls out of that window, move
the case to a newer year.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

DATASET_FILE = Path(__file__).parent / "golden_dataset.json"

DataTool = Literal["get_quote", "get_financial_facts", "list_recent_filings"]


class ExpectedFigure(BaseModel):
    """A number with one right answer, which some key figure must equal."""

    description: str = Field(min_length=1)
    value: float


class GoldenCase(BaseModel):
    """One eval question.

    Attributes:
        id: A short stable name, used in test IDs and the results file.
        question: What is asked. This is the turn that is checked.
        setup: Questions asked first on the same thread, unchecked, so `question` can
            rely on memory (a follow-up).
        good_answer: What a good answer needs, in words. For people reading the results.
        expected_tools: Data tools that must be called this turn.
        forbid_data_tools: True if no data tool may be called (an off-topic question).
        expected_figures: Figures the answer must contain, exactly.
        min_key_figures: The answer must have at least this many key figures. For
            numbers that change, such as a price, where no exact value can be expected.
        expect_no_key_figures: True if the answer must contain no number at all.
        expected_source_fragment: Some source URL must contain this text.
        forbidden_phrases: Phrases the summary must not contain, in any letter case.
        judge_relevancy: Whether the judged relevancy metric is scored. Off for a question
            the desk should decline: a polite refusal is the right answer, but a judge
            rightly marks it as not relevant to the question.
    """

    id: str = Field(pattern=r"^[a-z0-9_]+$")
    question: str = Field(min_length=1)
    setup: list[str] = []
    good_answer: str = Field(min_length=1)
    expected_tools: list[DataTool] = []
    forbid_data_tools: bool = False
    expected_figures: list[ExpectedFigure] = []
    min_key_figures: int = Field(default=0, ge=0)
    expect_no_key_figures: bool = False
    expected_source_fragment: str | None = None
    forbidden_phrases: list[str] = []
    judge_relevancy: bool = True


class GoldenDataset(BaseModel):
    """The whole file."""

    cases: list[GoldenCase] = Field(min_length=1)


def load_golden_dataset(path: Path = DATASET_FILE) -> list[GoldenCase]:
    """Read and validate the golden dataset.

    Raises:
        pydantic.ValidationError: The file does not fit the schema above.
    """
    return GoldenDataset.model_validate_json(path.read_text(encoding="utf-8")).cases
