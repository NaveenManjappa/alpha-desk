"""An eval report as Markdown, for reading on GitHub.

The JSON file is for comparing runs with code; this one is for people. GitHub renders the
tables, and the `<details>` blocks fold each case's answer and steps away until clicked.
"""

from evals.report import CaseResult, EvalReport


def report_markdown(report: EvalReport) -> str:
    """The whole report: the run's details and score, a table of cases, then each case."""
    mean = f"{report.mean_relevancy:.2f}" if report.mean_relevancy is not None else "n/a"
    cost = report.agent_cost_usd + report.judge_cost_usd
    lines = [
        f"# Eval run {report.finished_at:%Y-%m-%d %H:%M} UTC",
        "",
        f"**Score: {report.score:.1%}** of checks passed. "
        f"**Cases passed: {report.cases_passed}/{report.cases_total}.** "
        f"Mean relevancy: {mean}.",
        "",
        "| Agent model | Judge model | System prompt | Estimated cost |",
        "|---|---|---|---|",
        f"| {report.agent_model} | {report.judge_model} | `{report.system_prompt_sha256}` "
        f"| ${cost:.4f} |",
        "",
        "## Cases",
        "",
        "| Result | Case | Checks | Relevancy | Tools called |",
        "|---|---|---|---|---|",
    ]
    for case in report.cases:
        passed_checks = sum(check.passed for check in case.checks)
        relevancy = f"{case.relevancy.score:.2f}" if case.relevancy else "not scored"
        tools = ", ".join(case.tools_called) or "none"
        lines.append(
            f"| {_verdict(case)} | [{case.id}](#{case.id}) | {passed_checks}/{len(case.checks)} "
            f"| {relevancy} | {_cell(tools)} |"
        )
    lines.append("")
    for case in report.cases:
        lines += _case_section(case)
    return "\n".join(lines)


def _case_section(case: CaseResult) -> list[str]:
    """One case: its question, every check, the judge's reason, then the answer and steps."""
    lines = [
        f'<a id="{case.id}"></a>',
        "",
        f"## {_verdict(case)} {case.id}",
        "",
        f"> {case.question}",
        "",
        "| Check | Result | Detail |",
        "|---|---|---|",
    ]
    lines += [
        f"| {_cell(check.name)} | {'pass' if check.passed else '**fail**'} "
        f"| {_cell(check.detail)} |"
        for check in case.checks
    ]
    if case.relevancy:
        result = "pass" if case.relevancy.passed else "**fail**"
        lines.append(
            f"| relevancy {case.relevancy.score:.2f}, needs {case.relevancy.threshold} "
            f"| {result} | {_cell(case.relevancy.reason)} |"
        )
    lines.append("")
    if case.error:
        lines += [f"**No answer:** {case.error}", ""]
    if case.answer:
        lines += _answer_details(case)
    if case.steps:
        lines += [
            "<details><summary>Steps</summary>",
            "",
            *[f"{number}. `{_code(step)}`" for number, step in enumerate(case.steps, 1)],
            "",
            "</details>",
            "",
        ]
    return lines


def _answer_details(case: CaseResult) -> list[str]:
    """The answer as the user saw it, folded away."""
    assert case.answer is not None
    answer = case.answer
    lines = [
        "<details><summary>Answer</summary>",
        "",
        answer.summary,
        "",
        f"Verified: {answer.verified}. Tokens: {case.total_tokens:,}. "
        f"Cost: ${case.estimated_cost_usd:.4f}.",
        "",
    ]
    if answer.key_figures:
        lines += ["| Label | Value | Unit | Period | Source |", "|---|---|---|---|---|"]
        lines += [
            f"| {_cell(f.label)} | {f.value:,} | {_cell(f.unit)} | {_cell(f.period)} "
            f"| [link]({f.source_url}) |"
            for f in answer.key_figures
        ]
        lines.append("")
    if answer.sources:
        lines += ["Sources:", "", *[f"- {source}" for source in answer.sources], ""]
    lines += ["</details>", ""]
    return lines


def _verdict(case: CaseResult) -> str:
    return "✅ PASS" if case.passed else "❌ FAIL"


def _cell(text: str) -> str:
    """Text safe inside a table cell: a `|` would end the cell, a newline the row."""
    return text.replace("|", "\\|").replace("\n", " ")


def _code(text: str) -> str:
    """Text safe inside inline code: a backtick would end it."""
    return text.replace("`", "'").replace("\n", " ")
