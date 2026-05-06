from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class CommentCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)


class CommentResponse(BaseModel):
    id: int
    fir_id: int
    user_id: int
    content: str
    created_at: datetime
    author_name: Optional[str] = None

    class Config:
        from_attributes = True
