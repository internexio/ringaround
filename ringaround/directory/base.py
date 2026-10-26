from typing import Protocol
from ringaround.models import Contractor, ProjectRequest


class DirectoryProvider(Protocol):
    async def find_contractors(
        self,
        project: ProjectRequest,
        limit: int = 20,
    ) -> list[Contractor]:
        """Search for contractors matching the project's category and zip code."""
        ...
