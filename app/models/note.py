from pydantic import BaseModel, field_validator
from typing import Dict, List, Optional
from datetime import datetime
from uuid import UUID

class NoteBase(BaseModel):
    raw_text: str
    summary: Optional[str] = None
    source_url: Optional[str] = None
    source_type: Optional[str] = None
    personal_insight: Optional[str] = None
    topic_id: Optional[UUID] = None
    embedding: Optional[List[float]] = None
    facets: Optional[Dict[str, List[str]]] = None

    @field_validator("embedding", mode="before")
    @classmethod
    def parse_embedding(cls, v):
        if isinstance(v, str):
            v = v.strip("[]")
            if not v:
                return []
            return [float(x) for x in v.split(",")]
        return v

class NoteInput(NoteBase):
    pass

class NoteOutput(NoteBase):
    id: UUID
    created_at: datetime
