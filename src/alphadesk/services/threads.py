"""Deleting a conversation, which is kept in two places: its checkpoints, and the list."""

import logging
from collections.abc import Awaitable, Callable

from alphadesk.repositories.threads import ThreadRepository

logger = logging.getLogger(__name__)

# Deletes everything the agent saved for a thread. In the app this is
# `graph.checkpointer.delete_checkpoints` with the checkpointer already filled in.
DeleteCheckpoints = Callable[[str], Awaitable[None]]


class ThreadService:
    """Deletes conversations. Permanent: there is no undo."""

    def __init__(self, threads: ThreadRepository, delete_checkpoints: DeleteCheckpoints) -> None:
        """Args:
        threads: The list of conversations.
        delete_checkpoints: Deletes a thread's messages. A function, so this module needs
            no LangGraph import. It must accept a thread that has none.
        """
        self._threads = threads
        self._delete_checkpoints = delete_checkpoints

    async def delete(self, thread_id: str) -> None:
        """Delete a conversation. Deleting one that does not exist succeeds.

        The messages go first. If the second step fails, the conversation is still listed,
        so the user can delete it again. The other order could leave messages that nothing
        points to.

        Raises:
            StorageError: One of the two could not be deleted.
        """
        await self._delete_checkpoints(thread_id)
        await self._threads.delete(thread_id)
        logger.info("Thread %s deleted.", thread_id)
