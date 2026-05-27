from pydantic import BaseModel
from typing import Optional
from uuid import UUID


class RelationBase(BaseModel):
    source_note_id: UUID
    target_note_id: UUID
    relation_type: str  # 'related_to' | 'extends' | 'contradicts' | 'depends_on'
    score: float = 1.0
    user_id: Optional[UUID] = None


class RelationCreate(RelationBase):
    pass


class RelationSchema(RelationBase):
    id: UUID
