"""Shared response types (guide 05 §3): UTC `Z` timestamps, finite numbers, paginated lists."""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import BaseModel, Field, PlainSerializer, WithJsonSchema


def _utc_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


UtcDateTime = Annotated[
    datetime,
    PlainSerializer(_utc_z, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "format": "date-time", "description": "UTC ISO-8601 ending in Z"}),
]


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None = Field(description="Opaque signed cursor for the next page; null at the end")
