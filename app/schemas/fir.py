from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from app.models.fir import FIRStatus, FIRCategory, FIRPriority


class FIRBase(BaseModel):
    title: str = Field(..., max_length=200, description="Short title for the FIR")
    description: str = Field(..., description="Detailed description of the incident")


class FIRCreate(FIRBase):
    incident_date: Optional[datetime] = None
    incident_location: Optional[str] = Field(None, max_length=500)
    category: FIRCategory = FIRCategory.other
    priority: FIRPriority = FIRPriority.medium
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class FIRResponse(FIRBase):
    id: int
    tracking_number: str
    citizen_id: int
    status: FIRStatus
    category: FIRCategory
    priority: FIRPriority
    incident_date: Optional[datetime] = None
    incident_location: Optional[str] = None
    assigned_officer_id: Optional[int] = None
    officer_notes: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    created_at: datetime
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class FIRDetailResponse(FIRResponse):
    """Extended response with nested comments and evidence."""
    comments: List["CommentResponse"] = []
    evidence: List["EvidenceResponse"] = []
    citizen_name: Optional[str] = None
    officer_name: Optional[str] = None


class FIRStatusUpdate(BaseModel):
    status: FIRStatus
    officer_notes: Optional[str] = None


class FIRAssignOfficer(BaseModel):
    officer_id: int


class FIRSearch(BaseModel):
    """Query parameters for searching FIRs."""
    status: Optional[FIRStatus] = None
    category: Optional[FIRCategory] = None
    priority: Optional[FIRPriority] = None
    assigned_officer_id: Optional[int] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    search: Optional[str] = None  # Search in title/description


# Avoid circular import — import these at the bottom
from app.schemas.comment import CommentResponse
from app.schemas.evidence import EvidenceResponse

# Rebuild the model to resolve forward references
FIRDetailResponse.model_rebuild()
