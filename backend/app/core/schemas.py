"""Shared request-schema building blocks. Requests forbid unknown fields."""

from __future__ import annotations

from datetime import date
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=70)]
Icon = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4)]
Note = Annotated[str, StringConstraints(max_length=500)]
# Strict: JSON strings such as "3" are rejected for integer fields (no lax coercion).
Revision = Annotated[int, Field(strict=True, ge=0)]
Workload = Literal["normal", "increased", "excluded"]


class ScheduleIn(Strict):
    weekdays: list[Annotated[int, Field(strict=True, ge=1, le=7)]] = Field(min_length=1, max_length=7)
    starts_on: date | None = None
    ends_on: date | None = None

    @field_validator("weekdays")
    @classmethod
    def _unique(cls, v: list[int]) -> list[int]:
        if len(set(v)) != len(v):
            raise ValueError("weekdays must be unique")
        return v


class RevisionIn(Strict):
    revision: Revision
