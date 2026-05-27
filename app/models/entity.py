from pydantic import BaseModel, field_validator
from typing import List, Optional
from uuid import UUID

class EntityBase(BaseModel):
    name: str
    type: str # 'concept' | 'technology' | 'project' | 'person'
    user_id: Optional[UUID] = None
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

class EntityCreate(EntityBase):
    pass

class EntitySchema(EntityBase):
    id: UUID
