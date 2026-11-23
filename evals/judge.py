"""The one judged check: DeepEval's answer relevancy metric, scored by an LLM judge.

Relevance has no single right answer, so code cannot check it. A judge model reads the
question and the answer, splits the answer into statements and marks each as relevant
or not. The score is the share of relevant statements, from 0 to 1. Run it twice on
the same answer and the score may differ a little, so the threshold leaves some slack
(ADR 008).

DeepEval would pick its own OpenAI model from `OPENAI_API_KEY`. Instead `FactoryJudge`
hands it a model from our model factory, so the judge follows our provider settings
(OpenAI or Azure OpenAI), and its tokens and cost are logged like every other model call.
"""

import logging
from typing import Any

from deepeval.metrics import AnswerRelevancyMetric
from deepeval.models import DeepEvalBaseLLM
from deepeval.test_case import LLMTestCase
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from pydantic import BaseModel

from alphadesk.domain.answer import Answer
from alphadesk.domain.usage import ModelPrice
from alphadesk.services.usage import estimate_cost_usd

logger = logging.getLogger(__name__)

METRIC_NAME = "answer_relevancy"

# The lowest passing score. Below 1 on purpose: a correct, cited answer often carries a
# statement the judge finds only loosely relevant, such as which filing a figure is from.
RELEVANCY_THRESHOLD = 0.7


class JudgedScore(BaseModel):
    """A judged metric's verdict on one answer.

    Attributes:
        metric: Which metric, e.g. "answer_relevancy".
        score: From 0 to 1.
        threshold: The lowest passing score.
        passed: `score >= threshold`.
        reason: The judge's explanation, for a person reading the results.
    """

    metric: str
    score: float
    threshold: float
    passed: bool
    reason: str


class FactoryJudge(DeepEvalBaseLLM):
    """A DeepEval judge backed by a chat model from `get_chat_model`.

    DeepEval calls `a_generate` with a prompt and, for most steps, a Pydantic `schema` the
    reply must fit. With a schema the reply is returned as an instance of it; without
    one, as text.

    Attributes:
        input_tokens: Tokens sent to the judge so far, over every call.
        output_tokens: Tokens the judge has written so far.
    """

    def __init__(self, model: BaseChatModel, model_name: str, price: ModelPrice) -> None:
        """Args:
        model: From `get_chat_model`.
        model_name: Shown in the results file.
        price: From `get_model_price`, for the cost in the log.
        """
        self._chat_model = model
        self._model_name = model_name
        self._price = price
        self.input_tokens = 0
        self.output_tokens = 0
        super().__init__(model_name)

    def load_model(self, *args: Any, **kwargs: Any) -> Any:
        """The model DeepEval stores; it is never called directly by DeepEval.

        Typed `Any` because DeepEval's own hint says it returns a `DeepEvalBaseLLM`, while
        its docs, rightly, return the underlying model.
        """
        return self._chat_model

    def get_model_name(self, *args: Any, **kwargs: Any) -> str:
        return self._model_name

    def generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        """Not used: the evals measure with `a_measure`, which calls `a_generate`."""
        raise NotImplementedError("FactoryJudge is async only. Use the metric's a_measure.")

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None) -> Any:
        """Ask the judge model, returning text, or an instance of `schema` if one is given.

        Raises:
            ValueError: The reply did not fit `schema`. DeepEval reports it as a failed
                measurement.
        """
        if schema is None:
            reply = await self._chat_model.ainvoke(prompt)
            self._log_usage(reply)
            return reply.text
        # include_raw keeps the model's own message, which carries the token counts.
        # Function calling works with any Pydantic schema DeepEval sends.
        structured = self._chat_model.with_structured_output(
            schema, method="function_calling", include_raw=True
        )
        result = await structured.ainvoke(prompt)
        assert isinstance(result, dict)  # include_raw=True always returns a dict
        self._log_usage(result["raw"])
        if result["parsed"] is None:
            raise ValueError(f"The judge's reply did not fit {schema.__name__}.") from result.get(
                "parsing_error"
            )
        return result["parsed"]

    def _log_usage(self, message: Any) -> None:
        """Add one call's tokens to the totals and log them with their estimated cost."""
        if not isinstance(message, AIMessage) or message.usage_metadata is None:
            logger.warning("The judge model reported no token usage.")
            return
        input_tokens = message.usage_metadata["input_tokens"]
        output_tokens = message.usage_metadata["output_tokens"]
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        logger.info(
            "Judge call: %d input tokens, %d output tokens, about $%.6f.",
            input_tokens,
            output_tokens,
            estimate_cost_usd(input_tokens, output_tokens, self._price),
        )


async def judge_relevancy(judge: FactoryJudge, question: str, answer: Answer) -> JudgedScore:
    """Score how relevant the answer is to the question.

    A new metric each time: a DeepEval metric keeps its last score on itself, so sharing
    one between cases would mix their results.

    Args:
        judge: The judge model.
        question: What was asked, with any earlier turns (see `judge_input`).
        answer: The agent's answer.
    """
    metric = AnswerRelevancyMetric(
        threshold=RELEVANCY_THRESHOLD, model=judge, include_reason=True, async_mode=True
    )
    test_case = LLMTestCase(input=question, actual_output=answer_as_text(answer))
    score = await metric.a_measure(test_case, _show_indicator=False)
    return JudgedScore(
        metric=METRIC_NAME,
        score=score,
        threshold=RELEVANCY_THRESHOLD,
        passed=score >= RELEVANCY_THRESHOLD,
        reason=metric.reason or "",
    )


def judge_input(setup: list[str], question: str) -> str:
    """The question as the judge sees it, with earlier turns for a follow-up.

    "And its net income?" alone names no company, so without the earlier question the
    judge could not tell whether an answer about Apple is relevant.
    """
    if not setup:
        return question
    earlier = "\n".join(f"- {turn}" for turn in setup)
    return f"Earlier questions in this conversation:\n{earlier}\n\nQuestion: {question}"


def answer_as_text(answer: Answer) -> str:
    """The answer as one text, as a reader sees it: the summary, key figures and sources.

    The figures matter to relevance: "What was Apple's revenue?" is answered by the
    figure, not by the summary, which holds no numbers. So do the sources: a filings
    answer has no figures, and its links to the filings are the answer.
    """
    lines = [answer.summary]
    if answer.key_figures:
        lines.append("Key figures:")
        lines += [
            f"- {figure.label}: {figure.value:,} {figure.unit} ({figure.period})"
            for figure in answer.key_figures
        ]
    if answer.sources:
        lines.append("Sources:")
        lines += [f"- {source}" for source in answer.sources]
    return "\n".join(lines)
