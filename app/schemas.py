from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TrackSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    artist: str
    album: str | None
    duration_seconds: float | None
    mime_type: str
    file_size: int
    created_at: datetime


class SearchResponse(BaseModel):
    query: str
    count: int
    items: list[TrackSummary]


class PlaybackResponse(BaseModel):
    track: TrackSummary
    url: str
    expires_in: int = Field(ge=1, le=3600)
