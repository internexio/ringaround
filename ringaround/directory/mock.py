"""
Mock directory — returns a fixed roster of contractors with known personas.
Useful for integration tests that run the full job pipeline offline.
"""
from __future__ import annotations
import asyncio
from ringaround.models import Contractor, ProjectRequest

_ROSTER = [
    {"name": "Pacific Northwest Bath Co",  "phone": "+12065550101", "persona": "quick_quoter"},
    {"name": "Summit Remodeling LLC",      "phone": "+12065550102", "persona": "chatty"},
    {"name": "Cascade Home Services",      "phone": "+12065550103", "persona": "too_busy"},
    {"name": "Rainier Contractors Inc",    "phone": "+12065550104", "persona": "refused"},
    {"name": "Puget Builders",             "phone": "+12065550105", "persona": "out_of_area"},
    {"name": "Olympic Home Improvement",   "phone": "+12065550106", "persona": "unavailable"},
]


class MockDirectoryProvider:
    async def find_contractors(
        self,
        project: ProjectRequest,
        limit: int = 20,
    ) -> list[Contractor]:
        await asyncio.sleep(0.01)
        return [
            Contractor(
                name=c["name"],
                phone=c["phone"],
                zip_code=project.zip_code,
                category=project.category,
                source="mock_directory",
                mock_persona=c["persona"],
            )
            for c in _ROSTER[:limit]
        ]
