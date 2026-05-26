from pydantic import BaseModel, field_validator
from typing import List, Optional
from uuid import UUID

class TopicBase(BaseModel):
    name: str
    parent_id: Optional[UUID] = None
    description: Optional[str] = None
    notion_page_id: Optional[str] = None
    embedding: Optional[List[float]] = None

    @field_validator("embedding", mode="before")
    @classmethod
    def parse_embedding(cls, v):
        if isinstance(v, str):
            v = v.strip("[]")
            if not v:
                return []
            return [float(x) for x in v.split(",")]
        return v

class TopicCreate(TopicBase):
    pass

class TopicSchema(TopicBase):
    id: UUID
