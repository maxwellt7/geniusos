"""Flatten the nested Limitless ContentNode hierarchy into ordered utterances,
preserving speaker attribution and millisecond offsets."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass
class FlatUtterance:
    sequence: int
    node_type: str | None
    speaker_name: str | None
    speaker_identifier: str | None
    text: str
    start_time: datetime | None
    end_time: datetime | None
    start_offset_ms: int | None
    end_offset_ms: int | None


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def flatten_content_nodes(contents: list[dict[str, Any]] | None) -> list[FlatUtterance]:
    """Depth-first traversal of ContentNode trees into a flat utterance list."""
    utterances: list[FlatUtterance] = []

    def visit(node: dict[str, Any]) -> None:
        text = (node.get("content") or "").strip()
        if text:
            utterances.append(
                FlatUtterance(
                    sequence=len(utterances),
                    node_type=node.get("type"),
                    speaker_name=node.get("speakerName"),
                    speaker_identifier=node.get("speakerIdentifier"),
                    text=text,
                    start_time=parse_iso(node.get("startTime")),
                    end_time=parse_iso(node.get("endTime")),
                    start_offset_ms=node.get("startOffsetMs"),
                    end_offset_ms=node.get("endOffsetMs"),
                )
            )
        for child in node.get("children") or []:
            visit(child)

    for node in contents or []:
        visit(node)
    return utterances
