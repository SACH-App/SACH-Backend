from pydantic import BaseModel
from typing import Optional
from datetime import datetime


class EvidenceResponse(BaseModel):
    id: int
    fir_id: int
    uploaded_by: int
    file_url: str
    file_name: str
    file_type: str
    file_size: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True
