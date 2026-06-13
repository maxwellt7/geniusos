"""Custom Graphiti entity types for the lifelog domain.

These are intentionally attribute-free: they classify entities into typed
labels (Person, Organization, ...) without per-entity attribute extraction.
Attribute models require json_schema constrained decoding to come back flat;
with json_object-mode providers (Theo) the LLM returns nested maps that Neo4j
rejects as property values.
"""

from pydantic import BaseModel


class Person(BaseModel):
    """A person mentioned in or participating in a conversation."""


class Organization(BaseModel):
    """A company, team, or institution mentioned in conversation."""


class Project(BaseModel):
    """A project, initiative, or piece of work being discussed."""


class Topic(BaseModel):
    """A subject or theme of discussion (e.g. marketing strategy, hiring)."""


class Place(BaseModel):
    """A physical or virtual location mentioned in conversation."""


ENTITY_TYPES = {
    "Person": Person,
    "Organization": Organization,
    "Project": Project,
    "Topic": Topic,
    "Place": Place,
}
