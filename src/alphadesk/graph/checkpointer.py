"""The checkpointer: where the agent's state is saved after every step.

A checkpointer gives a graph short-term memory. After each step (the user's input, every
model call, every tool call) LangGraph writes a checkpoint: a snapshot of the whole state,
filed under the run's `thread_id`. The next run on the same thread loads the latest
checkpoint first, so the model sees the earlier turns. A different `thread_id` starts from
nothing.

For now the checkpoints live in a dict in this process, so they vanish when it exits.
"""

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

# Our own classes that may be rebuilt from a checkpoint, as (module, class name).
# A checkpoint stores the agent's `structured_response`, an `AnswerDraft`. LangGraph only
# rebuilds classes it is told are safe, because loading a checkpoint must never run code
# named in the data. Messages and other LangChain types are already on its safe list.
_ALLOWED_TYPES = [("alphadesk.domain.answer", "AnswerDraft")]


def create_checkpointer() -> InMemorySaver:
    """Create an in-memory checkpointer.

    Returns:
        A fresh, empty checkpointer. Pass it to `create_research_agent`, and keep using the
        same one for a conversation: memory lives inside this object.
    """
    return InMemorySaver(serde=JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_TYPES))
