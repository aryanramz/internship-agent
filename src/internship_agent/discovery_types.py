"""Provider-independent retrieval evidence; no persistence or raw responses."""
from dataclasses import dataclass

from .models import Job


@dataclass(frozen=True)
class SourcePage:
    jobs: list[Job]
    next_cursor: dict | None = None
    complete: bool = True
    authoritative: bool = False
    raw_count: int = 0
    rejected_count: int = 0
    closed: tuple[dict, ...] = ()
