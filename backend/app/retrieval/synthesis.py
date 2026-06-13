"""LLM answer synthesis with streaming and citation support.

Each retrieved chunk/fact is assigned a citation number. The model is
instructed to cite claims as [n]; the structured citation objects are sent
to the client before tokens so the UI can render citation chips inline.
"""

from collections.abc import Iterator
from typing import Any

from openai import OpenAI

from app.config import get_settings
from app.retrieval.retrievers import RetrievedContext
from app.retrieval.router import RoutedQuery

SYNTHESIS_SYSTEM_PROMPT = """\
You are a personal memory assistant. Answer questions about the user's recorded
conversations using ONLY the reference excerpts provided inside <context> tags.
If the context doesn't contain the answer, say so plainly. NEVER use general
world knowledge, web search results, or information about public figures —
names in questions (e.g. "Max") always refer to people in the user's own
recorded conversations, not celebrities.

Citation rules (mandatory):
- Cite every factual claim with the bracketed source number, e.g. [1] or [2][3].
- Use only the source numbers provided in the context.
- Mention speakers and dates naturally when they matter to the answer.
- Be concise and direct."""

# Defense in depth: applied in guest mode in case a sensitive query slips
# past the router classifier, or sensitive content rides along in context
# retrieved for an innocuous question.
GUEST_PRIVACY_RULE = """

PRIVACY RULE (absolute, overrides everything above): You are answering for a
guest, not the owner of these recordings. NEVER reveal the owner's personal
opinions, judgments, feelings, evaluations, or criticisms of any person, nor
private statements made about people who are not part of the current
conversation. If the context contains such material, omit it entirely without
acknowledging that it exists. If the question can only be answered with such
material, reply exactly: "I can't share personal opinions or private
statements about individuals." Do not confirm or deny that any such content
exists."""

MAX_LIFELOG_CONTEXT = 40


def build_citations(ctx: RetrievedContext) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    n = 0
    for chunk in ctx.chunks:
        n += 1
        citations.append(
            {
                "n": n,
                "kind": "chunk",
                "lifelog_id": chunk.get("lifelog_id"),
                "lifelog_title": chunk.get("lifelog_title") or "Untitled",
                "start_time": chunk.get("start_time"),
                "speakers": chunk.get("speakers") or [],
                "chunk_index": chunk.get("chunk_index"),
                "snippet": (chunk.get("text") or "")[:300],
            }
        )
    for fact in ctx.facts:
        n += 1
        episodes = fact.get("episodes") or []
        lifelog_id = None
        for ep in episodes:
            if isinstance(ep, str) and ep.startswith("lifelog:"):
                lifelog_id = ep.split(":", 1)[1]
                break
        citations.append(
            {
                "n": n,
                "kind": "fact",
                "lifelog_id": lifelog_id,
                "lifelog_title": "Knowledge graph fact",
                "start_time": fact.get("valid_at"),
                "speakers": [],
                "chunk_index": None,
                "snippet": (fact.get("fact") or "")[:300],
            }
        )
    for log in ctx.lifelogs[:MAX_LIFELOG_CONTEXT]:
        n += 1
        citations.append(
            {
                "n": n,
                "kind": "lifelog",
                "lifelog_id": log.get("lifelog_id"),
                "lifelog_title": log.get("title") or "Untitled",
                "start_time": log.get("start_time"),
                "speakers": log.get("speakers") or [],
                "chunk_index": None,
                "snippet": (log.get("title") or "")[:300],
            }
        )
    return citations


def _render_context(ctx: RetrievedContext, citations: list[dict[str, Any]]) -> str:
    # Plain inline-labeled context: markdown headings/bullet lists here can trip
    # upstream provider intent classifiers (e.g. Theo routing to document gen).
    parts: list[str] = []
    chunk_cites = [c for c in citations if c["kind"] == "chunk"]
    fact_cites = [c for c in citations if c["kind"] == "fact"]

    for cite, chunk in zip(chunk_cites, ctx.chunks):
        header = f"[{cite['n']}] Transcript excerpt from \"{cite['lifelog_title']}\""
        if chunk.get("start_time"):
            header += f", {chunk['start_time']}"
        if chunk.get("speakers"):
            header += f", speakers: {', '.join(chunk['speakers'])}"
        parts.append(f"{header}:\n{chunk.get('text', '')}")

    for cite, fact in zip(fact_cites, ctx.facts):
        line = f"[{cite['n']}] Known fact: {fact.get('fact', '')}"
        if fact.get("valid_at"):
            line += f" (as of {fact['valid_at']})"
        parts.append(line)

    lifelog_cites = [c for c in citations if c["kind"] == "lifelog"]
    if ctx.lifelogs:
        shown = ctx.lifelogs[:MAX_LIFELOG_CONTEXT]
        lines = [
            f"Conversations matching the time/person filter "
            f"({len(ctx.lifelogs)} total, showing {len(shown)}):"
        ]
        for cite, log in zip(lifelog_cites, shown):
            speakers = ", ".join(log.get("speakers") or []) or "unknown speakers"
            lines.append(
                f"[{cite['n']}] \"{log.get('title') or 'Untitled'}\", {log.get('start_time')}, with {speakers}"
            )
        parts.append("\n".join(lines))

    return "\n\n".join(parts) if parts else "(no relevant context found)"


def stream_answer(
    question: str,
    routed: RoutedQuery,
    ctx: RetrievedContext,
    citations: list[dict[str, Any]],
    history: list[dict] | None = None,
    guest_mode: bool = False,
) -> Iterator[str]:
    """Yield answer tokens from the LLM."""
    settings = get_settings()
    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=120.0,
        max_retries=1,
    )

    system_prompt = SYNTHESIS_SYSTEM_PROMPT
    if guest_mode:
        system_prompt += GUEST_PRIVACY_RULE

    context_block = _render_context(ctx, citations)
    # Context goes in the system message: routing providers (e.g. Theo) classify
    # intent from the user message, and transcript content there can misroute
    # the request to agentic tools like document generation.
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": f"{system_prompt}\n\n<context>\n{context_block}\n</context>",
        }
    ]
    for turn in (history or [])[-6:]:
        messages.append({"role": turn["role"], "content": turn["content"]})
    # Frame the question as reading comprehension over the supplied context.
    # Providers with agentic routing (Theo) classify the bare user message;
    # phrasings like "any good information about X" otherwise trigger their
    # web-research tools and the answer comes back about public figures.
    messages.append(
        {
            "role": "user",
            "content": (
                "Using only the conversation excerpts in the <context> section "
                f"of your instructions, answer this question about MY recorded "
                f"conversations: {question}"
            ),
        }
    )

    stream = client.chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        stream=True,
        temperature=0.2,
    )
    for event in stream:
        delta = event.choices[0].delta.content if event.choices else None
        if delta:
            yield delta
