"""Semantic chunking: group sequential utterances into coherent chunks.

Limitless marks topic shifts with heading nodes (heading1/heading2/heading3),
so headings act as hard topic boundaries. Within a topic, utterances are
packed up to a token budget with a small utterance overlap between adjacent
chunks to preserve context across boundaries.
"""

from dataclasses import dataclass, field
from datetime import datetime

import tiktoken

from app.ingestion.parser import FlatUtterance

TARGET_TOKENS = 600
MAX_TOKENS = 800
OVERLAP_UTTERANCES = 2

HEADING_TYPES = {"heading1", "heading2", "heading3"}

_encoder = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_encoder.encode(text))


@dataclass
class ChunkDraft:
    heading: str | None
    utterances: list[FlatUtterance] = field(default_factory=list)

    @property
    def speakers(self) -> list[str]:
        seen: list[str] = []
        for u in self.utterances:
            name = u.speaker_name or ("You" if u.speaker_identifier == "user" else None)
            if name and name not in seen:
                seen.append(name)
        return seen

    @property
    def start_time(self) -> datetime | None:
        times = [u.start_time for u in self.utterances if u.start_time]
        return min(times) if times else None

    @property
    def end_time(self) -> datetime | None:
        times = [u.end_time for u in self.utterances if u.end_time]
        return max(times) if times else None

    @property
    def first_sequence(self) -> int | None:
        return self.utterances[0].sequence if self.utterances else None

    @property
    def last_sequence(self) -> int | None:
        return self.utterances[-1].sequence if self.utterances else None

    def render(self) -> str:
        lines: list[str] = []
        if self.heading:
            lines.append(f"# {self.heading}")
        for u in self.utterances:
            speaker = u.speaker_name or ("You" if u.speaker_identifier == "user" else "Unknown")
            lines.append(f"{speaker}: {u.text}")
        return "\n".join(lines)


def chunk_utterances(utterances: list[FlatUtterance]) -> list[ChunkDraft]:
    """Split a lifelog's utterances into semantically coherent chunks."""
    chunks: list[ChunkDraft] = []
    current = ChunkDraft(heading=None)
    current_tokens = 0
    heading: str | None = None

    def finalize(next_heading: str | None) -> None:
        nonlocal current, current_tokens
        if current.utterances:
            chunks.append(current)
            overlap = current.utterances[-OVERLAP_UTTERANCES:] if next_heading is None else []
            current = ChunkDraft(heading=next_heading or heading, utterances=list(overlap))
            current_tokens = sum(count_tokens(u.text) for u in current.utterances)
        else:
            current = ChunkDraft(heading=next_heading or heading)
            current_tokens = 0

    for u in utterances:
        if u.node_type in HEADING_TYPES:
            heading = u.text
            finalize(next_heading=heading)
            continue

        tokens = count_tokens(u.text)
        if current_tokens + tokens > MAX_TOKENS and current_tokens >= TARGET_TOKENS // 2:
            finalize(next_heading=None)
        current.utterances.append(u)
        current_tokens += tokens

    if current.utterances:
        chunks.append(current)

    # Drop chunks that are only overlap or trivially small fragments.
    return [c for c in chunks if count_tokens(c.render()) > 10]
