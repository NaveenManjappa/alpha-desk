"""Eval results: one record per case, an overall score, and a file to compare runs with.

Each run is saved in `evals/results/`, named by when it ran, twice: as JSON, to compare
runs with code, and as Markdown, to read on GitHub (`evals/markdown.py`). To see whether a
change helped, compare the score and the per-case checks of two runs. Each file also
records a hash of the system prompt, so you can tell which prompt a run used.
"""

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from pydantic import AwareDatetime, BaseModel

from alphadesk.config.settings import Settings
from alphadesk.domain.answer import Answer
from alphadesk.domain.usage import ModelPrice
from alphadesk.services.usage import estimate_cost_usd
from evals.checks import Check
from evals.dataset import GoldenCase
from evals.harness import CaseRun
from evals.judge import FactoryJudge, JudgedScore

RESULTS_DIR = Path(__file__).parent / "results"


class CaseResult(BaseModel):
    """Everything about one case, as saved in the results file.

    Attributes:
        id: The case's ID.
        question: What was asked.
        passed: True if every exact check passed and, when scored, the judged one too.
        checks: The exact checks, in order.
        relevancy: The judged score, or None when it was not scored.
        tools_called: The data tools the agent called.
        answer: The agent's answer, figures and sources included, or None without one.
        steps: What happened in the checked turn, one line per message.
        error: Why there is no answer, or None.
        total_tokens: The agent's tokens on the checked turn. The judge's are counted in
            the report, not here.
        estimated_cost_usd: The agent's cost on the checked turn.
    """

    id: str
    question: str
    passed: bool
    checks: list[Check]
    relevancy: JudgedScore | None
    tools_called: list[str]
    answer: Answer | None
    steps: list[str]
    error: str | None
    total_tokens: int
    estimated_cost_usd: float


class EvalReport(BaseModel):
    """One eval run.

    Attributes:
        finished_at: When the run ended (UTC). Also the results file's name.
        agent_model: The model the agent ran on.
        judge_model: The model that scored relevancy.
        system_prompt_sha256: First 12 hex digits of the system prompt's hash. Two runs
            with the same value used the same prompt.
        score: The share of all checks passed, exact and judged together, from 0 to 1.
            Finer than the share of cases passed, so a prompt change that breaks one
            check in several cases shows clearly.
        cases_passed: How many cases passed every check.
        cases_total: How many cases ran.
        mean_relevancy: The mean judged score over the cases that were scored, or None.
        agent_cost_usd: Estimated cost of the agent's checked turns.
        judge_cost_usd: Estimated cost of the judge's calls.
        cases: Each case's result.
    """

    finished_at: AwareDatetime
    agent_model: str
    judge_model: str
    system_prompt_sha256: str
    score: float
    cases_passed: int
    cases_total: int
    mean_relevancy: float | None
    agent_cost_usd: float
    judge_cost_usd: float
    cases: list[CaseResult]


@dataclass
class EvalSession:
    """What one `make eval` run collects as it goes, for the summary and the results file.

    Attributes:
        settings: The settings the run used.
        judge: The judge model, which also counts its own tokens.
        results: Each finished case, in the order they ran.
    """

    settings: Settings
    judge: FactoryJudge
    results: list[CaseResult] = field(default_factory=list)


def case_result(
    case: GoldenCase, run: CaseRun, checks: Sequence[Check], relevancy: JudgedScore | None
) -> CaseResult:
    """Put one case's run and verdicts together."""
    passed = all(check.passed for check in checks) and (relevancy is None or relevancy.passed)
    return CaseResult(
        id=case.id,
        question=case.question,
        passed=passed,
        checks=list(checks),
        relevancy=relevancy,
        tools_called=run.tools_called,
        answer=run.answer,
        steps=run.steps,
        error=run.error,
        total_tokens=run.usage.total_tokens if run.usage else 0,
        estimated_cost_usd=run.usage.estimated_cost_usd if run.usage else 0.0,
    )


def build_report(
    cases: Sequence[CaseResult],
    *,
    agent_model: str,
    judge_model: str,
    system_prompt: str,
    judge_tokens: tuple[int, int],
    judge_price: ModelPrice,
) -> EvalReport:
    """Score a run.

    Args:
        cases: Every case's result.
        agent_model: The agent's model name.
        judge_model: The judge's model name.
        system_prompt: The agent's system prompt, hashed to tell prompts apart.
        judge_tokens: `(input_tokens, output_tokens)` the judge used in the whole run.
        judge_price: The judge model's price.
    """
    verdicts = [check.passed for case in cases for check in case.checks]
    verdicts += [case.relevancy.passed for case in cases if case.relevancy is not None]
    relevancy_scores = [case.relevancy.score for case in cases if case.relevancy is not None]
    return EvalReport(
        finished_at=datetime.now(UTC),
        agent_model=agent_model,
        judge_model=judge_model,
        system_prompt_sha256=hashlib.sha256(system_prompt.encode()).hexdigest()[:12],
        score=sum(verdicts) / len(verdicts) if verdicts else 0.0,
        cases_passed=sum(case.passed for case in cases),
        cases_total=len(cases),
        mean_relevancy=(
            sum(relevancy_scores) / len(relevancy_scores) if relevancy_scores else None
        ),
        agent_cost_usd=sum(case.estimated_cost_usd for case in cases),
        judge_cost_usd=estimate_cost_usd(*judge_tokens, judge_price),
        cases=list(cases),
    )


def save_report(report: EvalReport, markdown: str, directory: Path = RESULTS_DIR) -> list[Path]:
    """Write the run as JSON and as Markdown, both named by when the run finished.

    Args:
        report: The scored run.
        markdown: The same run for people to read, from `evals.markdown.report_markdown`.
        directory: Where to write. `evals/results/` by default.

    Returns:
        The paths written: the JSON file, then the Markdown file.
    """
    directory.mkdir(parents=True, exist_ok=True)
    stem = f"eval-{report.finished_at:%Y%m%dT%H%M%SZ}"
    json_path = directory / f"{stem}.json"
    json_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    markdown_path = directory / f"{stem}.md"
    markdown_path.write_text(markdown, encoding="utf-8")
    return [json_path, markdown_path]


def summary_lines(report: EvalReport) -> list[str]:
    """The run as lines for the terminal: one per case, then the overall score."""
    lines: list[str] = []
    for case in report.cases:
        passed_checks = sum(check.passed for check in case.checks)
        relevancy = f", relevancy {case.relevancy.score:.2f}" if case.relevancy else ""
        verdict = "PASS" if case.passed else "FAIL"
        lines.append(
            f"{verdict}  {case.id:<30} checks {passed_checks}/{len(case.checks)}{relevancy}"
        )
        lines += [f"        x {c.name}: {c.detail}" for c in case.checks if not c.passed]
        if case.relevancy and not case.relevancy.passed:
            lines.append(
                f"        x relevancy below {case.relevancy.threshold}: {case.relevancy.reason}"
            )
    mean = f"{report.mean_relevancy:.2f}" if report.mean_relevancy is not None else "n/a"
    lines += [
        "",
        f"Score: {report.score:.1%} of checks passed. "
        f"Cases passed: {report.cases_passed}/{report.cases_total}. Mean relevancy: {mean}.",
        f"Prompt {report.system_prompt_sha256}. Agent {report.agent_model}, "
        f"judge {report.judge_model}. Cost about "
        f"${report.agent_cost_usd + report.judge_cost_usd:.4f}.",
    ]
    return lines
