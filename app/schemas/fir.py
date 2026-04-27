from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from app.models.fir import FIRStatus

class FIRBase(BaseModel):
    description: str = Field(..., description="Detailed description of the incident")

class FIRCreate(FIRBase):
    pass

class FIRResponse(FIRBase):
    id: int
    tracking_number: str
    citizen_id: int
    status: FIRStatus
    assigned_officer_id: Optional[int]
    created_at: datetime

    class Config:
        from_attributes = True

class FIRStatusUpdate(BaseModel):
    status: FIRStatus
