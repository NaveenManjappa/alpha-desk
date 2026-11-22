"""The events `POST /chat` streams to the client (phase 1 spec, Slice 11).

A chat turn can take many seconds: the model thinks, tools call Finnhub and SEC EDGAR, and
the grounding check may ask the model again. Streaming events keeps the user informed
while that happens, instead of a silent wait for one big response.

Every stream ends with exactly one `final` or one `error` event. Before that come any
number of `status` and `token` events.

Each event has a `type` field naming it, so a client can tell them apart after parsing the
JSON. The TypeScript models in `web/` mirror these classes; change both together.
"""

from typing import Literal

from pydantic import BaseModel

from alphadesk.domain.answer import Answer


class StatusEvent(BaseModel):
    """A data tool is about to run.

    Attributes:
        tool: The tool's name, e.g. "get_quote". Stable, for code to match on.
        message: A short, plain description for the user, e.g. "Getting the latest share
            price". Written by code, not by the model.
    """

    type: Literal["status"] = "status"
    tool: str
    message: str


class TokenEvent(BaseModel):
    """A piece of text the model wrote, sent as soon as it arrives.

    The answer itself is not streamed this way: it comes whole in the `final` event, after
    the grounding check. Token events carry any text the model writes on the way, which may
    be none at all.
    """

    type: Literal["token"] = "token"
    text: str


class FinalEvent(BaseModel):
    """The finished answer, after the grounding check. Always the last event of a run."""

    type: Literal["final"] = "final"
    answer: Answer


class ErrorEvent(BaseModel):
    """The run could not finish. Always the last event of a run.

    Attributes:
        message: Safe to show the user. Never contains a stack trace or internal detail;
            those go to the server log.
    """

    type: Literal["error"] = "error"
    message: str


# What the agent sends while it works, before the answer.
ProgressEvent = StatusEvent | TokenEvent

# Every event a chat stream can contain.
ChatEvent = StatusEvent | TokenEvent | FinalEvent | ErrorEvent
