"""Query intent classification: route to semantic / relational / temporal layers."""

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import anthropic
from openai import OpenAI

from app.config import get_settings

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """\
You classify user questions about their personal conversation history (lifelogs)
to route them to the right retrieval system.

Intents:
- "semantic": meaning-based questions about what was discussed
- "relational": multi-hop questions about relationships between people,
  organizations, projects, or topics
- "temporal": questions whose primary constraint is a time range or a list of
  conversations (browse/list/show questions, "what did I talk about on <date>")

ALWAYS extract date bounds when the question mentions or implies a time period
(a specific day means start_date = end_date = that day). Today is {today}.
EXCEPTION: pure recency phrasing ("most recent", "latest", "last conversation")
is NOT a date range — leave start_date/end_date null; retrieval returns the
most recent conversations first, which may be from days ago.

Follow-ups: when the question is a follow-up like "tell me more", "go on",
"what else", or "expand on that", DO NOT treat it as a new standalone
question — build search_query from the topic of the previous turns in the
conversation, broadened to pull in additional related material (synonyms,
adjacent subtopics, people involved). Keep any date bounds from the earlier
question.

Privacy: set privacy_sensitive to true when the question asks for:
(a) the owner's personal opinions, judgments, feelings, evaluations,
criticisms, or private statements ABOUT a specific person or about the asker
("what do you/does he think of me", "what was said about Sarah", "does Max
like working with John", "any complaints about anyone"); OR
(b) the owner's private personal affairs: finances (income, salary, spending,
debts, investments, deals, account balances, net worth, "financial
situation"), health or medical matters, intimate or relationship details,
family conflicts, legal issues, or credentials/passwords.
NOT privacy sensitive: questions about shared events, meetings, decisions,
work topics, daily summaries, or the owner's own conduct, skills, habits, or
style ("how does Max handle leadership", "what did I talk about today").
Set subject_person to the person the sensitive question targets ("me" if it's
the asker, the owner's name for questions about the owner's affairs).

Output ONLY a JSON object with EXACTLY these seven keys and nothing else:
{{"intent": "semantic"|"relational"|"temporal", "search_query": "rewritten standalone search query", "start_date": "YYYY-MM-DD"|null, "end_date": "YYYY-MM-DD"|null, "speaker": "person name"|null, "privacy_sensitive": true|false, "subject_person": "name"|null}}

Examples:
Q: "What did we discuss about the marketing strategy?"
{{"intent": "semantic", "search_query": "marketing strategy discussion", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": false, "subject_person": null}}
Q: "Who did Sarah recommend for the engineering role and where have they worked?"
{{"intent": "relational", "search_query": "Sarah recommendation engineering role candidate work history", "start_date": null, "end_date": null, "speaker": "Sarah", "privacy_sensitive": false, "subject_person": null}}
Q: "What conversations did I have on May 6th 2025?"
{{"intent": "temporal", "search_query": "conversations on May 6 2025", "start_date": "2025-05-06", "end_date": "2025-05-06", "speaker": null, "privacy_sensitive": false, "subject_person": null}}
Q: "Show me everything I talked about with John last week" (today 2026-06-12)
{{"intent": "temporal", "search_query": "conversations with John", "start_date": "2026-06-01", "end_date": "2026-06-07", "speaker": "John", "privacy_sensitive": false, "subject_person": null}}
Q: "Summarize my most recent conversation"
{{"intent": "temporal", "search_query": "most recent conversation", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": false, "subject_person": null}}
Q: "What does Max really think about me?"
{{"intent": "semantic", "search_query": "opinions about the asker", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": true, "subject_person": "me"}}
Q: "What's Max's financial situation?"
{{"intent": "semantic", "search_query": "finances income investments money", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": true, "subject_person": "Max"}}
Q: "Tell me more" (previous turn asked about the marketing strategy meeting)
{{"intent": "semantic", "search_query": "marketing strategy campaign planning budget follow-up discussion", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": false, "subject_person": null}}
Q: "What did he say about Sarah behind her back?"
{{"intent": "semantic", "search_query": "statements about Sarah", "start_date": null, "end_date": null, "speaker": null, "privacy_sensitive": true, "subject_person": "Sarah"}}
Q: "Is there any good information about how Max handles leadership from today?" (today 2026-06-12)
{{"intent": "semantic", "search_query": "Max leadership style management approach", "start_date": "2026-06-12", "end_date": "2026-06-12", "speaker": null, "privacy_sensitive": false, "subject_person": null}}"""


@dataclass
class RoutedQuery:
    intent: str = "semantic"
    search_query: str = ""
    start_date: datetime | None = None
    end_date: datetime | None = None
    speaker: str | None = None
    privacy_sensitive: bool = False
    subject_person: str | None = None
    raw: dict = field(default_factory=dict)


def _user_tz():
    """The user's timezone: USER_TIMEZONE (IANA name) or the system local zone.

    Date math must happen in the user's timezone, not UTC — "today" at 8pm
    EDT is already tomorrow in UTC, which made same-day filters miss
    everything.
    """
    settings = get_settings()
    if settings.user_timezone:
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(settings.user_timezone)
        except Exception:
            logger.warning("Invalid USER_TIMEZONE %r; using system local", settings.user_timezone)
    return datetime.now().astimezone().tzinfo


def _parse_date(value: str | None, end_of_day: bool = False) -> datetime | None:
    """Interpret a YYYY-MM-DD date as a day boundary in the user's timezone,
    returned as an aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=_user_tz())
        if end_of_day:
            dt = dt.replace(hour=23, minute=59, second=59)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


# Conservative fallback when LLM classification fails entirely: only flag
# questions that overtly ask for opinions/statements about a person.
_SENSITIVE_PATTERNS = re.compile(
    r"(?:think|feel)s?\s+(?:of|about)\s+"
    r"|opinions?\s+(?:of|about|on)\s+(?:me|him|her|them|[A-Z]\w+)"
    r"|(?:say|says|said|talk|talks|talked|talking)\s+about\s+(?:me|him|her|them)\b"
    r"|behind\s+(?:my|his|her|their|\w+'?s)\s+back"
    r"|(?:like|love|hate|trust)s?\s+(?:me|him|her|them)\b"
    r"|complain(?:t|ts|ed|ing)?\s+about"
    r"|financ|salar|income|net\s+worth|debt|invest|bank\s+account"
    r"|health|medical|diagnos|therap|medicat",
    re.IGNORECASE,
)


def _heuristic_sensitive(question: str) -> bool:
    return bool(_SENSITIVE_PATTERNS.search(question))


# Structured-output schema for Claude: the API validates the response against
# this, so the seven-key contract can't come back malformed.
_ROUTER_SCHEMA = {
    "type": "object",
    "properties": {
        "intent": {"type": "string", "enum": ["semantic", "relational", "temporal"]},
        "search_query": {"type": "string"},
        "start_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "end_date": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "speaker": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "privacy_sensitive": {"type": "boolean"},
        "subject_person": {"anyOf": [{"type": "string"}, {"type": "null"}]},
    },
    "required": [
        "intent",
        "search_query",
        "start_date",
        "end_date",
        "speaker",
        "privacy_sensitive",
        "subject_person",
    ],
    "additionalProperties": False,
}


def _classify_claude(settings, system_prompt: str, turns: list[dict]) -> dict | None:
    """Classify via Claude with schema-enforced JSON output."""
    client = anthropic.Anthropic(
        api_key=settings.anthropic_api_key, timeout=25.0, max_retries=0
    )
    for attempt in range(2):
        try:
            resp = client.messages.create(
                model=settings.router_model,
                max_tokens=1024,
                system=system_prompt,
                messages=turns,
                output_config={"format": {"type": "json_schema", "schema": _ROUTER_SCHEMA}},
            )
            text = next(b.text for b in resp.content if b.type == "text")
            return json.loads(text)
        except Exception:
            logger.exception("Claude router classification failed (attempt %d)", attempt + 1)
    return None


def _classify_openai(settings, system_prompt: str, turns: list[dict]) -> dict | None:
    """Classify via an OpenAI-compatible provider (legacy path)."""
    # Fail fast: classification is one small call. If the provider is having a
    # slow/flaky period, fall back to the heuristic quickly rather than
    # stalling the whole request behind long SDK retries.
    client = OpenAI(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        timeout=25.0,
        max_retries=0,
    )
    messages = [{"role": "system", "content": system_prompt}, *turns]
    for attempt in range(2):
        try:
            resp = client.chat.completions.create(
                model=settings.router_model,
                messages=messages,
                response_format={"type": "json_object"},
                temperature=0,
            )
            content = resp.choices[0].message.content.strip()
            # Tolerate providers that wrap JSON in code fences or append prose:
            # parse the first JSON object found and ignore anything after it.
            start = content.find("{")
            if start == -1:
                raise ValueError(f"No JSON object in router response: {content[:200]}")
            data, _ = json.JSONDecoder().raw_decode(content[start:])
            return data
        except Exception:
            logger.exception("Router classification failed (attempt %d)", attempt + 1)
    return None


def classify_query(question: str, history: list[dict] | None = None) -> RoutedQuery:
    settings = get_settings()

    system_prompt = ROUTER_SYSTEM_PROMPT.format(
        today=datetime.now(_user_tz()).strftime("%Y-%m-%d (%A)")
    )
    turns: list[dict] = []
    for turn in (history or [])[-4:]:
        turns.append({"role": turn["role"], "content": turn["content"]})
    # The Messages API requires the first message to be a user turn.
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    turns.append({"role": "user", "content": question})

    if settings.router_model.startswith("claude"):
        data = _classify_claude(settings, system_prompt, turns)
    else:
        data = _classify_openai(settings, system_prompt, turns)

    if data is None:
        # LLM classification unavailable: fall back to semantic retrieval and a
        # conservative keyword heuristic for the privacy flag, so transient
        # provider failures don't block innocuous questions in guest mode.
        return RoutedQuery(
            intent="semantic",
            search_query=question,
            privacy_sensitive=_heuristic_sensitive(question),
        )

    return RoutedQuery(
        intent=data.get("intent", "semantic"),
        search_query=data.get("search_query") or question,
        start_date=_parse_date(data.get("start_date")),
        end_date=_parse_date(data.get("end_date"), end_of_day=True),
        speaker=data.get("speaker"),
        privacy_sensitive=bool(data.get("privacy_sensitive")),
        subject_person=data.get("subject_person"),
        raw=data,
    )
