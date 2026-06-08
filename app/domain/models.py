from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Book:
    id: int
    title: str
    premise: str
    status: str


@dataclass(frozen=True)
class Volume:
    id: int
    book_id: int
    title: str
    goal: str
    start_chapter: int
    end_chapter: int


@dataclass(frozen=True)
class StoryArc:
    id: int
    book_id: int
    volume_id: int
    title: str
    goal: str
    pressure: str
    start_chapter: int
    end_chapter: int


@dataclass(frozen=True)
class ChapterPlan:
    id: int
    book_id: int
    volume_id: int
    arc_id: int
    chapter_no: int
    title: str
    objective: str
    allowed_reveals: str
    forbidden_reveals: str
    pace_limit: str
    status: str


@dataclass(frozen=True)
class Artifact:
    id: int
    book_id: int
    chapter_no: int | None
    artifact_type: str
    status: str
    content: str


@dataclass(frozen=True)
class PipelineRun:
    id: int
    book_id: int
    chapter_no: int
    status: str
