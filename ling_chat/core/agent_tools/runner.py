"""Stub SimpleAgentRunner — upstream agent_tools module is incomplete.

This keeps the build green until upstream provides the real implementation.
The stub is a no-op: enrich_context_if_needed returns the context unchanged.
"""

from ling_chat.core.logger import logger


class SimpleAgentRunner:
    """Stub: no-op agent runner.

    Upstream added a reference to this class but hasn't committed the
    full agent_tools package yet.  This stub passes context through
    unchanged so the rest of the system continues to work.
    """

    def __init__(self, llm_model, game_status):
        self._llm_model = llm_model
        self._game_status = game_status
        logger.debug("SimpleAgentRunner stub initialized (upstream WIP)")

    async def enrich_context_if_needed(
        self,
        current_context,
        user_message,
        client_id=None,
        code_mode=False,
    ):
        """No-op: return context as-is until upstream ships the real agent tools."""
        return current_context
