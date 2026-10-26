from typing import Protocol
from ringaround.models import TurnIntent, CallState, ProjectRequest


class LLMProvider(Protocol):
    async def classify_intent(self, vendor_text: str, state: CallState) -> TurnIntent:
        """Classify what the vendor just said."""
        ...

    async def generate_agent_turn(
        self, state: CallState, project: ProjectRequest, context: dict
    ) -> str:
        """Generate the agent's next utterance."""
        ...
